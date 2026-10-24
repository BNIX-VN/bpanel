"""Website mode "proxy": nginx in front of any http(s) address (operator,
2026-10-24). Who may name a private address, and what reaches proxy_pass."""
import pytest

from app.services import nginx


def _vhost(url, **kwargs):
    return nginx.render_vhost("example.test", "/home/bp_example_test/example.test",
                              app_type="proxy", php_version=None, proxy_url=url, **kwargs)


def test_the_address_goes_to_proxy_pass_with_the_visitors_host():
    rendered = _vhost("http://127.0.0.1:8080")
    assert "proxy_pass http://127.0.0.1:8080;" in rendered
    assert "proxy_set_header Host $host;" in rendered
    assert "proxy_set_header Upgrade $http_upgrade;" in rendered
    # The ACME challenge stays on disk, ahead of the proxy.
    assert "/.well-known/acme-challenge/" in rendered


def test_an_https_upstream_gets_its_own_name_and_may_keep_its_host():
    rendered = _vhost("https://backend.example.net/app/", proxy_preserve_host=False)
    assert "proxy_pass https://backend.example.net/app/;" in rendered
    assert "proxy_ssl_server_name on;" in rendered
    assert "proxy_set_header Host $proxy_host;" in rendered


def test_an_application_site_still_proxies_to_its_port():
    rendered = nginx.render_vhost("example.test", "/home/bp_example_test/example.test",
                                  app_type="application", php_version=None, app_port=21000)
    assert "proxy_pass http://127.0.0.1:21000;" in rendered
    assert "proxy_set_header Host $host;" in rendered


@pytest.mark.parametrize("url", [
    "", "ftp://example.net", "http://example.net; return 200",
    "http://example.net/$request_uri", "http://exa mple.net", "http://example.net:99999",
    "http://example.net/'x'{}", "javascript:alert(1)",
])
def test_nothing_nginx_would_read_as_syntax(url):
    with pytest.raises(ValueError):
        nginx.validate_proxy_url(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:3000", "http://localhost:3000", "http://10.0.0.5", "http://[::1]:8080",
    "http://169.254.169.254/latest", "http://printer.local",
])
def test_a_customer_cannot_point_a_site_inside_the_server(url):
    with pytest.raises(ValueError, match="administrator"):
        nginx.validate_proxy_url(url, allow_private=False)
    # The administrator can.
    assert nginx.validate_proxy_url(url, allow_private=True) == url


def test_a_customer_can_point_a_site_at_a_public_address():
    assert nginx.validate_proxy_url("https://8.8.8.8/", allow_private=False) == "https://8.8.8.8/"
