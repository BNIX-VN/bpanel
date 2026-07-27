import pytest

from app.services import waf


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


def test_render_site_rules_includes_wp2shell_rules():
    content = waf.render_site_rules("example.com", ["wordpress-wp2shell"])

    assert "id:1000001" in content
    assert "id:1000002" in content
    assert "/wp-json/batch/v1" in content
    assert "/batch/v1" in content


def test_default_rules_do_not_scan_request_body_or_headers():
    content = waf.render_site_rules("example.com", [rule["id"] for rule in waf.DEFAULT_RULES])

    assert "REQUEST_BODY" not in content
    assert "REQUEST_HEADERS" not in content


def test_unknown_rule_ids_are_rejected():
    with pytest.raises(ValueError, match="Unknown WAF rule"):
        waf.validate_enabled_rule_ids(["joomla-sensitive-files"])


def test_access_log_parser_classifies_waf_blocks():
    parsed = waf._parse_access_log_line(
        "example.com",
        '49.37.10.172 - - [27/Jul/2026:04:13:34 +0000] "POST /xmlrpc.php HTTP/1.1" 403 0 "-" "curl/8.0"',
        1,
    )

    assert parsed is not None
    _, item = parsed
    assert item["verdict"] == "block"
    assert item["method"] == "POST"
    assert item["path"] == "/xmlrpc.php"
    assert item["reason"] == "Block WordPress XML-RPC"


def test_access_log_parser_classifies_wp2shell_blocks():
    parsed = waf._parse_access_log_line(
        "example.com",
        '49.37.10.172 - - [27/Jul/2026:04:13:34 +0000] "GET /wp-json/batch/v1?rest_route=/batch/v1 HTTP/1.1" 403 0 "-" "curl/8.0"',
        1,
    )

    assert parsed is not None
    _, item = parsed
    assert item["verdict"] == "block"
    assert item["path"] == "/wp-json/batch/v1?rest_route=/batch/v1"
    assert item["reason"] == "Block WordPress wp2shell probe"


def test_access_logs_filters_and_sorts(monkeypatch):
    site = type("Website", (), {"domain": "example.com"})()
    content = "\n".join(
        [
            '209.42.31.36 - - [27/Jul/2026:04:13:16 +0000] "GET /wp-login.php HTTP/1.1" 200 120 "-" "browser"',
            '49.37.10.172 - - [27/Jul/2026:04:13:34 +0000] "POST /xmlrpc.php HTTP/1.1" 403 0 "-" "curl/8.0"',
        ]
    )

    def fake_read_site_log(domain, kind, lines):
        assert domain == "example.com"
        assert kind == "access"
        assert lines == 5000
        return {"exists": True, "content": content}

    monkeypatch.setattr("app.services.nginx.read_site_log", fake_read_site_log)

    result = waf.access_logs([site], verdict="block", limit=50)

    assert result["total"] == 1
    assert result["scanned"] == 2
    assert result["items"][0]["ip"] == "49.37.10.172"
