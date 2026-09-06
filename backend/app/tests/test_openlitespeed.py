import pytest

from app.services import nginx
from app.services import openlitespeed as ols


def test_interface_matches_nginx_for_every_dispatch_call_site():
    """webserver.py forwards attribute lookups blindly (PEP 562) - a name
    nginx.py has and openlitespeed.py doesn't fails only at runtime, on
    whichever call site hits it first. Every name app.services.webserver's
    own docstring promises must exist on both backends."""
    required = [
        "render_vhost", "rewrite_vhost", "write_vhost", "delete_wordpress_vhost",
        "read_vhost_config", "read_site_log", "clear_site_log", "update_waf_block",
        "update_http_flood_block", "update_custom_block", "sync_http_flood_zones",
        "validate_http_flood_config", "http_flood_config_for_website", "vhost_exists",
        "ensure_proxy_upgrade_map",
    ]
    for name in required:
        assert hasattr(nginx, name), f"nginx.py is missing {name}"
        assert hasattr(ols, name), f"openlitespeed.py is missing {name}"

    # PHP versions and rewrite modes must mean the same thing on both.
    for const in ("ALLOWED_REWRITE_MODES", "ALLOWED_PHP_VERSIONS"):
        assert getattr(nginx, const) == getattr(ols, const), f"{const} differs between backends"

    # App types deliberately do NOT match: "application" (proxy a domain to a
    # locally installed app) is an nginx-only feature. An OLS server refuses
    # it outright rather than shipping a second, less tested proxy path.
    assert ols.ALLOWED_APP_TYPES == {"wordpress", "php", "static"}
    assert nginx.ALLOWED_APP_TYPES == ols.ALLOWED_APP_TYPES | {"application"}
    assert ols.PROXIED_APP_TYPES == set()

    # Both must declare whether certbot wires SSL into the vhost for them -
    # the SSL endpoints branch on it, and a missing attribute would silently
    # default to "yes" and leave an OLS site's certificate referenced by
    # nothing.
    assert nginx.SSL_WIRED_BY_CERTBOT is True
    assert ols.SSL_WIRED_BY_CERTBOT is False


def test_wordpress_vhost_renders_lsphp_and_lscache():
    rendered = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="wordpress",
        php_version="8.4",
    )

    assert "vhDomain                  example.test" in rendered
    assert "extprocessor lsphp84" in rendered
    assert "path                  /usr/local/lsws/lsphp84/bin/lsphp" in rendered
    assert "BPANEL LSCACHE BEGIN" in rendered
    assert "Content-Security-Policy: default-src 'self'" in rendered


def test_php_vhost_has_no_lscache_block():
    rendered = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
    )

    assert "BPANEL LSCACHE" not in rendered
    assert "extprocessor lsphp83" in rendered


def test_static_vhost_has_no_php_processor():
    rendered = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="static",
    )

    assert "extprocessor" not in rendered
    assert "Static site: no PHP processor needed" in rendered


def test_application_websites_are_refused_with_a_useful_message():
    """Creating one should say which server types support it, not just
    "unsupported app type"."""
    with pytest.raises(ValueError, match="only available on Nginx"):
        ols.render_vhost(
            "example.test", "/home/bp_example_test/example.test",
            app_type="application", app_port=3000,
        )


def test_http_flood_renders_nothing_even_when_enabled():
    """OpenLiteSpeed cannot count requests per client over a window. The
    per-vhost extprocessor this used to render throttled nothing measurable
    while making the panel report the site as protected - a decorative
    control is worse than an absent one.
    """
    for kwargs in (
        dict(app_type="wordpress", php_version="8.4"),
        dict(app_type="php", php_version="8.4"),
        dict(app_type="static"),
    ):
        rendered = ols.render_vhost(
            "example.test", "/home/bp_example_test/example.test",
            http_flood_enabled=True,
            http_flood_config={"access_limit_requests": 10, "connection_limit": 5},
            **kwargs,
        )
        assert "HTTP FLOOD" not in rendered, kwargs
        assert "extprocessor bpanel_hf" not in rendered, kwargs
    assert ols._http_flood_block("example.test", {}) == ""


def test_vhost_includes_alias_domains():
    rendered = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        aliases=["alias.test", "alias.test"],
    )

    assert rendered.count("vhAliases                 alias.test") == 1


def test_a_redirect_domain_gets_its_own_vhost_not_a_conditional_rule():
    """OpenLiteSpeed ignores RewriteCond in the rewrite blocks we generate.

    Verified on a live server: a condition that could never match still fired
    its rule, so a host-based `RewriteCond %{HTTP_HOST}` inside the main vhost
    301'd every hostname the site owned - the primary (where it looked like a
    harmless HTTP->HTTPS redirect and hid the bug) and, visibly wrong, every
    alias. Redirects therefore get a vhost of their own, exactly as nginx
    gives them their own server block, where an unconditional rule is right.
    """
    main = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        aliases=["alias.example.test"],
        redirects=["old.example.test"],
    )
    # The main vhost must not claim the redirect hostname, or it steals it
    # from the redirect vhost that is meant to answer for it.
    claimed = {line.split()[1] for line in main.splitlines() if line.startswith(("vhDomain", "vhAliases"))}
    assert claimed == {"example.test", "www.example.test", "alias.example.test"}
    # ...and carries no host-based condition, which would not work anyway.
    assert "HTTP_HOST" not in main

    redirect = ols.render_redirect_vhost(
        "old.example.test", "example.test", "/home/bp_example_test/example.test"
    )
    assert "vhDomain                  old.example.test" in redirect
    assert "vhAliases                 www.old.example.test" in redirect
    assert "RewriteRule ^(.*)$ https://example.test/$1 [R=301,L]" in redirect
    # Unconditional is correct here: this vhost only receives that hostname.
    # Checked as a directive, not a substring - the comment above explains why
    # RewriteCond is avoided and would otherwise match.
    directives = [line.strip() for line in redirect.splitlines() if not line.lstrip().startswith("#")]
    assert not [d for d in directives if d.startswith("RewriteCond")]
    # The ACME context has to come first, or the redirect would bounce Let's
    # Encrypt away and this domain could never join the certificate.
    assert redirect.index("acme-challenge") < redirect.index("RewriteRule")
    # Ownership marker, so a stale redirect vhost can be pruned later.
    assert "# BPANEL REDIRECT OWNER example.test" in redirect


def test_a_redirect_vhost_carries_the_sites_certificate_when_there_is_one():
    redirect = ols.render_redirect_vhost(
        "old.example.test", "example.test", "/home/bp_example_test/example.test",
        ssl_cert_path="/etc/letsencrypt/live/example.test/fullchain.pem",
        ssl_key_path="/etc/letsencrypt/live/example.test/privkey.pem",
    )
    assert "vhssl {" in redirect
    assert "certFile              /etc/letsencrypt/live/example.test/fullchain.pem" in redirect


def test_waf_block_toggles_the_modsecurity_module():
    on = ols.render_vhost(
        "example.test", "/home/bp_example_test/example.test",
        app_type="php", php_version="8.3", waf_enabled=True,
    )
    off = ols.render_vhost(
        "example.test", "/home/bp_example_test/example.test",
        app_type="php", php_version="8.3", waf_enabled=False,
    )

    assert "modsecurity           on" in on
    assert "BPANEL WAF BEGIN" not in off


def test_manual_ssl_writes_vhssl_block():
    rendered = ols.render_vhost(
        "example.test", "/home/bp_example_test/example.test",
        app_type="php", php_version="8.3",
        ssl_cert_path="/usr/local/lsws/conf/bpanel/ssl/sites/example.test/cert.crt",
        ssl_key_path="/usr/local/lsws/conf/bpanel/ssl/sites/example.test/privkey.key",
    )

    assert "vhssl {" in rendered
    assert "certFile              /usr/local/lsws/conf/bpanel/ssl/sites/example.test/cert.crt" in rendered


def test_vhost_exists_is_false_for_an_unrelated_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(ols, "OLS_VHOSTS_DIR", tmp_path)
    assert ols.vhost_exists("nope.test") is False
    (tmp_path / "there.test").mkdir()
    (tmp_path / "there.test" / "vhost.conf").write_text("x", encoding="utf-8")
    assert ols.vhost_exists("there.test") is True
    assert ols.vhost_exists("nope.test") is False


def test_invalid_app_type_is_rejected():
    with pytest.raises(ValueError):
        ols.render_vhost("example.test", "/home/x/example.test", app_type="not-a-real-type")


def test_invalid_php_version_is_rejected():
    with pytest.raises(ValueError):
        ols.render_vhost("example.test", "/home/x/example.test", app_type="php", php_version="4.0")


def test_validate_http_flood_config_clamps_out_of_range_values():
    result = ols.validate_http_flood_config({"access_limit_requests": -5, "connection_limit": 999999})

    assert result["access_limit_requests"] == 1
    assert result["connection_limit"] == 10000


def test_custom_directives_reject_a_dangerous_directive():
    with pytest.raises(ValueError):
        ols.validate_custom_directives("extprocessor evil {\n type proxy\n}")


def test_custom_directives_reject_unbalanced_braces():
    with pytest.raises(ValueError):
        ols.validate_custom_directives("foo {")


def _context_bodies(rendered: str) -> list[str]:
    """The body of each `context ... {` block in a rendered vhost."""
    bodies, depth, current = [], 0, None
    for line in rendered.splitlines():
        stripped = line.strip()
        if current is None and stripped.startswith("context ") and stripped.endswith("{"):
            current, depth = [], 1
            continue
        if current is not None:
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                bodies.append("\n".join(current))
                current = None
                continue
            current.append(line)
    return bodies


def test_each_context_has_at_most_one_rewrite_block():
    """OpenLiteSpeed keeps only the LAST rewrite block in a context and
    silently discards the others.

    Splitting `inherit` and our own rules into two blocks therefore threw the
    rules away. On a live server that meant a POST to xmlrpc.php answered 200
    with the full XML-RPC method list instead of being blocked, and it would
    have 404'd every Laravel/CodeIgniter route - those have no .htaccess to
    fall back on the way WordPress does.
    """
    cases = [
        dict(app_type="wordpress", php_version="8.4"),
        dict(app_type="php", php_version="8.4", rewrite_mode="laravel"),
        dict(app_type="php", php_version="8.4", rewrite_mode="codeigniter"),
        dict(app_type="php", php_version="8.4", rewrite_mode="none"),
        dict(app_type="static"),
    ]
    for kwargs in cases:
        rendered = ols.render_vhost("example.test", "/home/bp_example_test/example.test", **kwargs)
        for body in _context_bodies(rendered):
            count = len([l for l in body.splitlines() if l.strip().startswith("rewrite ")])
            assert count <= 1, f"{kwargs} rendered {count} rewrite blocks in one context"


def test_wordpress_sensitive_paths_are_blocked_with_an_access_control_context():
    """A RewriteRule with [F] does not block on OpenLiteSpeed - verified live,
    a POST to xmlrpc.php answered 200 with the full XML-RPC method list even
    with the rule rendered and the surrounding rewrite block working. Only an
    accessControl context actually returns 403, and it has to be declared
    before `context /` for the more specific match to win.
    """
    rendered = ols.render_vhost(
        "example.test", "/home/bp_example_test/example.test",
        app_type="wordpress", php_version="8.4",
    )
    for blocked in ("/xmlrpc.php", "/wp-config.php", "/readme.html", "/license.txt"):
        marker = f"context {blocked} {{"
        assert marker in rendered, f"{blocked} is not blocked"
        assert rendered.index(marker) < rendered.index("\ncontext / {"), (
            f"{blocked} must be declared before context /"
        )
    # The rule that silently did nothing must not come back.
    assert "RewriteRule ^xmlrpc" not in rendered


def test_laravel_rewrite_rules_survive_into_the_rewrite_block():
    rendered = ols.render_vhost(
        "example.test", "/home/bp_example_test/example.test",
        app_type="php", php_version="8.4", rewrite_mode="laravel",
    )
    body = next(b for b in _context_bodies(rendered) if "rewriteRules" in b)
    assert "RewriteRule ^(.*)$ index.php [QSA,L]" in body
    assert "inherit" in body


def test_letsencrypt_paths_reach_a_backend_certbot_cannot_wire(monkeypatch):
    """The panel runs as 'bpanel' and cannot stat /etc/letsencrypt/live, so
    the paths have to be passed, not discovered. Guessing with is_file() there
    raised PermissionError and made Install SSL a 500."""
    from app.api import websites
    from app.core.config import settings
    from types import SimpleNamespace

    site = SimpleNamespace(
        domain="example.test", ssl_mode="letsencrypt",
        ssl_cert_path=None, ssl_key_path=None, ssl_ca_path=None, ssl_source_domain=None,
    )
    monkeypatch.setattr(settings, "web_server", "openlitespeed")
    kwargs = websites._rewrite_ssl_kwargs(site)
    assert kwargs["ssl_cert_path"] == "/etc/letsencrypt/live/example.test/fullchain.pem"
    assert kwargs["ssl_key_path"] == "/etc/letsencrypt/live/example.test/privkey.pem"

    # nginx must keep getting nothing: certbot's plugin already wrote the
    # ssl_certificate lines into the vhost, and rewrite_vhost merges them back
    # out of it. Passing paths here would fight that.
    monkeypatch.setattr(settings, "web_server", "nginx")
    assert websites._rewrite_ssl_kwargs(site) == {}


def test_preserve_existing_ssl_reads_the_vhost_not_the_letsencrypt_dir(monkeypatch, tmp_path):
    """Carrying an existing certificate over must not touch root-only paths."""
    vhost_dir = tmp_path / "example.test"
    vhost_dir.mkdir()
    (vhost_dir / "vhost.conf").write_text(
        "docRoot /home/x/example.test/public_html\n"
        "vhssl {\n"
        "    keyFile               /etc/letsencrypt/live/example.test/privkey.pem\n"
        "    certFile              /etc/letsencrypt/live/example.test/fullchain.pem\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ols, "OLS_VHOSTS_DIR", tmp_path)
    monkeypatch.setattr(ols.settings, "command_dry_run", True)

    rendered = ols.rewrite_vhost(
        "example.test", "/home/bp_example_test/example.test",
        app_type="php", php_version="8.4", preserve_existing_ssl=True,
    )
    assert "certFile              /etc/letsencrypt/live/example.test/fullchain.pem" in rendered


def test_every_vhost_answers_on_www_like_nginx_does():
    """nginx._server_names puts <domain> and www.<domain> in every
    server_name. Without the same on OLS the listener maps only the bare
    domain and www falls through to whatever catches unmatched hostnames -
    LiteSpeed's stock Example page on a fresh box, another customer's site on
    a busy one.
    """
    for kwargs in (
        dict(app_type="wordpress", php_version="8.4"),
        dict(app_type="php", php_version="8.4"),
        dict(app_type="static"),
    ):
        rendered = ols.render_vhost("example.test", "/home/bp_example_test/example.test", **kwargs)
        assert "vhDomain                  example.test" in rendered
        assert "vhAliases                 www.example.test" in rendered, kwargs


def test_www_is_not_duplicated_when_passed_as_an_alias():
    rendered = ols.render_vhost(
        "example.test", "/home/bp_example_test/example.test",
        app_type="php", php_version="8.4", aliases=["www.example.test", "shop.example.test"],
    )
    assert rendered.count("vhAliases                 www.example.test") == 1
    assert "vhAliases                 shop.example.test" in rendered


def test_each_app_type_denies_what_its_nginx_template_denies():
    """A site must not be less protected just because it runs on OLS.

    The nginx templates deny with `location ... { deny all; }`; the OLS ones
    with accessControl contexts. Different syntax, same set - this compares
    them so the two cannot quietly drift.
    """
    import re
    from pathlib import Path

    nginx_dir = Path(ols.TEMPLATE_DIR).parent / "nginx"
    cases = {
        "wordpress": dict(app_type="wordpress", php_version="8.4"),
        "php": dict(app_type="php", php_version="8.4"),
        "static": dict(app_type="static"),
        # No "proxy" case: the application app type is nginx-only here.
    }
    # What the nginx template protects, reduced to a comparable idea.
    expected = {
        "wordpress": {"dotfiles", "secret-extensions", "uploads-php", "wp-internals", "exact-files"},
        "php": {"dotfiles", "secret-extensions"},
        "static": {"dotfiles", "secret-extensions", "scripts"},
    }

    def classify(rendered: str, is_nginx: bool) -> set[str]:
        found = set()
        blob = rendered
        if re.search(r"\\.\(\?!well-known\)|\(\?!well-known\)", blob):
            found.add("dotfiles")
        if "sql|bak|backup|old|orig|save|swp|swo|ini|log|conf|env|sh|inc" in blob:
            found.add("secret-extensions")
        if "uploads|files" in blob:
            found.add("uploads-php")
        if "wp-admin/includes|wp-includes" in blob:
            found.add("wp-internals")
        if "php|phtml|phar" in blob:
            found.add("scripts")
        if ("/xmlrpc.php" in blob and "/wp-config.php" in blob
                and "/readme.html" in blob and "/license.txt" in blob):
            found.add("exact-files")
        return found

    for name, kwargs in cases.items():
        nginx_src = (nginx_dir / f"{name}.conf.j2").read_text(encoding="utf-8")
        rendered = ols.render_vhost("example.test", "/home/bp_example_test/example.test", **kwargs)
        nginx_has = classify(nginx_src, True)
        ols_has = classify(rendered, False)
        assert nginx_has == expected[name], f"nginx {name} template changed: {nginx_has}"
        missing = nginx_has - ols_has
        assert not missing, f"OLS {name} does not protect: {missing}"


def test_deny_contexts_come_before_the_main_context():
    """OpenLiteSpeed picks the most specific context; a deny declared after
    `context /` never wins."""
    for kwargs in (
        dict(app_type="wordpress", php_version="8.4"),
        dict(app_type="php", php_version="8.4"),
        dict(app_type="static"),
    ):
        rendered = ols.render_vhost("example.test", "/home/bp_example_test/example.test", **kwargs)
        main = rendered.index("\ncontext / {")
        for line in rendered.splitlines():
            if line.startswith("context ") and "accessControl" not in line:
                continue
        last_deny = rendered.rindex("accessControl")
        assert last_deny < main, f"a deny context lands after context / for {kwargs}"


def test_the_dotfile_pattern_stays_anchored():
    """An unanchored pattern makes OLS treat the context as a directory and
    answer 301 to /.htaccess/ instead of 403 - seen on a live server."""
    assert ols._DOTFILES_EXCEPT_WELL_KNOWN.endswith(".*$")
