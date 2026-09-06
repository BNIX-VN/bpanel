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

    for const in ("PROXIED_APP_TYPES", "ALLOWED_APP_TYPES", "ALLOWED_REWRITE_MODES", "ALLOWED_PHP_VERSIONS"):
        assert getattr(nginx, const) == getattr(ols, const), f"{const} differs between backends"


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


def test_proxy_vhost_points_at_the_app_port():
    rendered = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="application",
        app_port=3000,
    )

    assert "address                 127.0.0.1:3000" in rendered
    assert "type                    proxy" in rendered
    assert "handler                 bpanel_app_example_test" in rendered


def test_proxy_vhost_without_a_port_is_rejected():
    with pytest.raises(ValueError, match="installed application"):
        ols.render_vhost(
            "example.test",
            "/home/bp_example_test/example.test",
            app_type="application",
        )


def test_vhost_includes_alias_domains():
    rendered = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        aliases=["alias.test", "alias.test"],
    )

    assert rendered.count("vhAliases                 alias.test") == 1


def test_redirect_domains_render_a_301_rewrite():
    rendered = ols.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        redirects=["old.example.test"],
    )

    assert "RewriteCond %{HTTP_HOST} ^(www\\.)?old.example.test$ [NC]" in rendered
    assert "RewriteRule ^(.*)$ https://example.test$1 [R=301,L]" in rendered


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
