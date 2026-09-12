import re
from pathlib import Path

import pytest

from app.services import waf

HELPER_SCRIPT = Path(__file__).resolve().parents[3] / "installer" / "files" / "bpanel-helper.sh"


def test_default_rules_only_cover_wordpress_laravel_and_php():
    definitions = waf.default_rule_definitions()

    assert {rule["category"] for rule in definitions} == {"Laravel", "PHP", "WordPress"}
    assert all(rule["enabled_default"] for rule in definitions)


def test_legacy_heavy_rule_ids_are_mapped_or_ignored():
    assert waf.validate_enabled_rule_ids([
        "general-sensitive-files",
        "general-path-traversal",
        "general-sqli",
        "general-xss",
        "general-command-injection",
    ]) == ["php-sensitive-files", "php-path-traversal", "php-runtime-probes"]


def test_render_site_rules_only_includes_selected_wordpress_rule():
    content = waf.render_site_rules("example.com", ["wordpress-sensitive-files"])

    assert "id:1001101" in content
    assert "id:1001201" not in content
    assert "id:1001301" not in content


def test_render_site_rules_includes_laravel_and_php_rules():
    content = waf.render_site_rules("example.com", ["laravel-sensitive-files", "php-sensitive-files"])

    assert "id:1001201" in content
    assert "id:1001301" in content


def test_default_rules_do_not_scan_request_body_or_headers():
    content = waf.render_site_rules("example.com", [rule["id"] for rule in waf.DEFAULT_RULES])

    assert "REQUEST_BODY" not in content
    assert "REQUEST_HEADERS" not in content


def test_waf_rules_are_phase_1():
    """A phase:2 rule is silently dead while request bodies are not buffered.

    The nginx connector never runs phase 2 when SecRequestBodyAccess is Off, so
    such a rule loads, reports as enabled in the UI, and never matches anything.
    Two shipped rules sat like that until 2026-09-13. If body access is ever
    turned on - which is what OWASP CRS needs - this test should be revisited
    together with the exclusion tuning, not simply deleted.
    """
    helper = HELPER_SCRIPT.read_text(encoding="utf-8")
    assert "SecRequestBodyAccess Off" in helper, (
        "request bodies are buffered now; revisit the phase of every shipped rule"
    )

    offenders = [
        rule["id"] for rule in waf.DEFAULT_RULES if "phase:1," not in rule["rules"]
    ]
    assert offenders == [], f"these rules would never fire: {offenders}"


def test_removing_site_rules_goes_through_the_helper(monkeypatch):
    calls = []

    def fake_privileged(helper_command, helper_args=None, **kwargs):
        calls.append((helper_command, list(helper_args or [])))
        return waf.CommandResult(command=helper_command, returncode=0,
                                 stdout="Removed WAF rules for example.com", stderr="")

    monkeypatch.setattr(waf.shell, "privileged", fake_privileged)
    note = waf.remove_site_rules("example.com")

    assert calls == [("waf-site-delete", ["example.com"])]
    assert "Removed" in note


def test_removing_site_rules_never_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("sudo went missing")

    monkeypatch.setattr(waf.shell, "privileged", boom)
    assert "could not remove" in waf.remove_site_rules("example.com")
    # A bogus domain is rejected quietly rather than blocking the deletion.
    assert waf.remove_site_rules("../../etc/nginx") == ""


def test_helper_will_not_delete_rules_a_vhost_still_uses():
    helper = HELPER_SCRIPT.read_text(encoding="utf-8")
    body = helper.split("delete_waf_site_rules()")[1].split("\n}\n")[0]
    # A missing modsecurity_rules_file fails `nginx -t`, so the next reload
    # anywhere would take every site on the box down.
    assert "modsecurity_rules_file" in body
    assert "deny " in body
    assert "require_domain" in body
    assert "waf-site-delete)" in helper
    # The check must read the config nginx actually loads. Grepping conf.d
    # instead matches the .conf.bak copies sitting next to every vhost, which
    # refused every real cleanup.
    assert "nginx -T" in body
    assert "/etc/nginx/conf.d/" not in body


def test_shipped_rules_match_the_helper_copy():
    """The rule text lives twice: in DEFAULT_RULES and in the installer helper.

    waf.py drives what a site gets and what the UI lists; the helper writes
    /etc/nginx/modsec/bpanel-default.conf for the server-wide config. They drift
    apart silently - a fix applied to one is invisible in the other.
    """
    helper = HELPER_SCRIPT.read_text(encoding="utf-8")
    block = helper.split("cat >/etc/nginx/modsec/bpanel-default.conf <<'RULES'")[1].split("\nRULES\n")[0]

    def rule_ids(text):
        return sorted(re.findall(r"id:(\d+)", text))

    def phases(text):
        return sorted(re.findall(r"id:(\d+),phase:(\d)", text))

    shipped = "\n".join(rule["rules"] for rule in waf.DEFAULT_RULES)
    assert rule_ids(block) == rule_ids(shipped)
    assert phases(block) == phases(shipped)


def test_unknown_rule_ids_are_rejected():
    with pytest.raises(ValueError, match="Unknown WAF rule"):
        waf.validate_enabled_rule_ids(["joomla-sensitive-files"])
