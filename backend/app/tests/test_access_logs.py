from types import SimpleNamespace

from app.services import waf


def test_access_logs_parse_and_filter(monkeypatch):
    site = SimpleNamespace(domain="example.com")
    sample = "\n".join([
        '1.2.3.4 - - [27/Jul/2026:12:00:00 +0700] "GET /wp-config.php HTTP/1.1" 403 153 "-" "curl/8.0" 0.012',
        '5.6.7.8 - - [27/Jul/2026:12:00:01 +0700] "POST /index.php HTTP/1.1" 200 321 "-" "Mozilla/5.0" 0.200',
        '9.8.7.6 - - [27/Jul/2026:12:00:02 +0700] "GET /admin HTTP/1.1" 500 10 "-" "Mozilla/5.0" 0.050',
    ])

    monkeypatch.setattr(waf.nginx, "read_site_log", lambda domain, kind, lines: {"exists": True, "content": sample})

    result = waf.access_logs([site], verdict="block", query="wp-config", limit=50, lines=5000)

    assert result["total"] == 1
    assert result["scanned"] == 3
    assert result["items"][0]["domain"] == "example.com"
    assert result["items"][0]["verdict"] == "block"
    assert result["items"][0]["reason"] == "Block WordPress config probe"


def test_clear_access_logs_calls_each_site(monkeypatch):
    cleared = []
    monkeypatch.setattr(waf.nginx, "clear_site_log", lambda domain, kind: cleared.append((domain, kind)))

    count = waf.clear_access_logs([
        SimpleNamespace(domain="example.com"),
        SimpleNamespace(domain="example.net"),
    ])

    assert count == 2
    assert cleared == [("example.com", "access"), ("example.net", "access")]
