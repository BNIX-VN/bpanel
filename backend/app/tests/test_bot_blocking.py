"""Per-website bot blocking: what gets stored, and what nginx ends up running."""

import pytest

from app.services import nginx


def test_a_pasted_list_is_split_on_whatever_separator_it_arrived_with():
    # Operators import these from tools like CPGuard, a blog post, or a
    # spreadsheet column, so the paste is never uniformly formatted.
    bots = nginx.normalize_blocked_bots(
        'AhrefsBot\nSemrushBot,  MJ12bot\n DotBot ;PetalBot\n\n"Bytespider"'
    )

    assert bots == ["AhrefsBot", "SemrushBot", "MJ12bot", "DotBot", "PetalBot", "Bytespider"]


def test_duplicates_are_dropped_case_insensitively_keeping_the_first_spelling():
    # A merged list routinely contains the same bot twice in different case;
    # emitting it twice would only make the regex longer.
    assert nginx.normalize_blocked_bots("AhrefsBot\nahrefsbot\nAHREFSBOT") == ["AhrefsBot"]


def test_names_are_matched_literally_not_as_patterns():
    """`bingbot/2.0` must not also match `bingbotX2Y0`.

    Real bot strings are full of regex metacharacters - "bingbot/2.0",
    "Sogou web spider/4.0" - and an unescaped dot is a wildcard. Verified
    against a running nginx: with the escaping below, `bingbotX2Y0` is served
    normally while `bingbot/2.0` gets 403.
    """
    block = nginx._bot_block(nginx.normalize_blocked_bots("bingbot/2.0"))

    assert r"bingbot/2\.0" in block
    assert "bingbot/2.0" not in block.replace(r"2\.0", "")


def test_one_regex_rather_than_one_if_per_bot():
    # nginx evaluates `if` blocks in order on every request; a few hundred of
    # them would be paid for on all traffic, not just the bots.
    block = nginx._bot_block(nginx.normalize_blocked_bots("A\nB\nC\nD"))

    assert block.count("if (") == 1
    assert "(A|B|C|D)" in block


def test_a_name_that_could_escape_the_nginx_string_is_refused():
    """The block is a double-quoted nginx string and `"` is not a regex
    metacharacter, so re.escape leaves it alone. Left unchecked, a bot name
    could close the string and have the remainder parsed as configuration."""
    with pytest.raises(ValueError):
        nginx.normalize_blocked_bots('evil") { return 200; } if ($host ~ "')
    with pytest.raises(ValueError):
        nginx.normalize_blocked_bots("back\\slash")
    with pytest.raises(ValueError):
        nginx.normalize_blocked_bots("tab\there")


def test_a_dollar_sign_cannot_become_an_nginx_variable():
    # nginx interpolates $variables inside double-quoted strings.
    block = nginx._bot_block(nginx.normalize_blocked_bots("bot$http_host"))

    assert r"\$http_host" in block


def test_the_list_is_capped():
    with pytest.raises(ValueError):
        nginx.normalize_blocked_bots(["bot%d" % i for i in range(nginx.MAX_BLOCKED_BOTS + 1)])
    with pytest.raises(ValueError):
        nginx.normalize_blocked_bots("x" * (nginx.MAX_BOT_NAME_LENGTH + 1))


def test_an_empty_list_removes_the_block_entirely():
    vhost = (
        "server {\n"
        "    server_name example.com;\n"
        "    # BPANEL BOT BLOCK BEGIN\n"
        '    if ($http_user_agent ~* "(AhrefsBot)") { return 403; }\n'
        "    # BPANEL BOT BLOCK END\n"
        "}\n"
    )

    cleaned = nginx._replace_bot_block(vhost, "")

    assert "BOT BLOCK" not in cleaned
    assert "server_name example.com;" in cleaned


def test_rewriting_replaces_rather_than_stacks_blocks():
    # Saving the list twice must not leave two blocks behind.
    vhost = "server {\n    server_name example.com;\n}\n"

    once = nginx._replace_bot_block(vhost, "AhrefsBot")
    twice = nginx._replace_bot_block(once, "SemrushBot")

    assert twice.count("# BPANEL BOT BLOCK BEGIN") == 1
    assert "SemrushBot" in twice
    assert "AhrefsBot" not in twice


def test_update_edits_the_existing_vhost_instead_of_re_rendering_it(tmp_path, monkeypatch):
    """Regression: this went out calling write_vhost(domain, <file content>).

    write_vhost's second parameter is root_path, and it re-renders the whole
    vhost from the template - so every apply failed with "root_path must be the
    managed root for this domain" and nothing was ever written. A dry-run test
    would not have caught it, because dry-run returns before touching the
    filesystem; this exercises the real path.

    Editing in place also matters on its own: a site whose vhost has been
    customised must keep those customisations when its bot list changes.
    """
    vhost = tmp_path / "example.com.conf"
    vhost.write_text(
        "server {\n"
        "    server_name example.com;\n"
        "    # a hand-added directive that must survive\n"
        "    client_max_body_size 64m;\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(nginx.settings, "command_dry_run", False)
    monkeypatch.setattr(nginx, "_vhost_path", lambda domain: vhost)
    monkeypatch.setattr(nginx, "_write_backup", lambda target, content: None)
    reloaded = []
    monkeypatch.setattr(nginx, "_test_and_reload", lambda target, previous: reloaded.append(target))

    nginx.update_bot_block("example.com", "AhrefsBot\nSemrushBot")

    written = vhost.read_text(encoding="utf-8")
    assert "(AhrefsBot|SemrushBot)" in written
    assert "client_max_body_size 64m;" in written
    assert reloaded, "nginx was never asked to test and reload the new config"


def test_the_block_sits_ahead_of_waf_and_flood():
    """Blocked traffic should cost as little as possible.

    Answering 403 on a regex match is cheaper than first running the request
    through ModSecurity's rule set and the rate-limit zones.
    """
    vhost = (
        "server {\n"
        "    server_name example.com;\n"
        "    # BPANEL HTTP FLOOD BEGIN\n"
        "    limit_req zone=x;\n"
        "    # BPANEL HTTP FLOOD END\n"
        "\n"
        "    # BPANEL WAF BEGIN\n"
        "    modsecurity on;\n"
        "    # BPANEL WAF END\n"
        "}\n"
    )

    result = nginx._replace_bot_block(vhost, "AhrefsBot")

    assert result.index("BOT BLOCK BEGIN") < result.index("HTTP FLOOD BEGIN")
    assert result.index("BOT BLOCK BEGIN") < result.index("WAF BEGIN")
