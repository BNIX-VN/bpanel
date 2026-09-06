from app.core.config import settings
from app.services import nginx, webserver


def test_active_name_defaults_to_nginx(monkeypatch):
    monkeypatch.setattr(settings, "web_server", "nginx")
    assert webserver.active_name() == "nginx"


def test_active_name_falls_back_to_nginx_for_unknown_value(monkeypatch):
    monkeypatch.setattr(settings, "web_server", "some-typo")
    assert webserver.active_name() == "nginx"


def test_active_name_falls_back_to_nginx_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "web_server", "")
    assert webserver.active_name() == "nginx"


def test_backend_is_the_nginx_module(monkeypatch):
    monkeypatch.setattr(settings, "web_server", "nginx")
    assert webserver.backend() is nginx


def test_function_attributes_forward_to_the_active_backend(monkeypatch):
    monkeypatch.setattr(settings, "web_server", "nginx")
    assert webserver.rewrite_vhost is nginx.rewrite_vhost
    assert webserver.write_vhost is nginx.write_vhost
    assert webserver.render_vhost is nginx.render_vhost
    assert webserver.delete_wordpress_vhost is nginx.delete_wordpress_vhost
    assert webserver.read_vhost_config is nginx.read_vhost_config
    assert webserver.read_site_log is nginx.read_site_log
    assert webserver.clear_site_log is nginx.clear_site_log
    assert webserver.sync_http_flood_zones is nginx.sync_http_flood_zones
    assert webserver.update_waf_block is nginx.update_waf_block
    assert webserver.update_http_flood_block is nginx.update_http_flood_block
    assert webserver.update_custom_block is nginx.update_custom_block
    assert webserver.validate_http_flood_config is nginx.validate_http_flood_config
    assert webserver.http_flood_config_for_website is nginx.http_flood_config_for_website
    assert webserver.vhost_exists is nginx.vhost_exists


def test_constant_attributes_forward_to_the_active_backend(monkeypatch):
    monkeypatch.setattr(settings, "web_server", "nginx")
    assert webserver.PROXIED_APP_TYPES == nginx.PROXIED_APP_TYPES
    assert webserver.ALLOWED_APP_TYPES == nginx.ALLOWED_APP_TYPES
    assert webserver.ALLOWED_REWRITE_MODES == nginx.ALLOWED_REWRITE_MODES
    assert webserver.ALLOWED_PHP_VERSIONS == nginx.ALLOWED_PHP_VERSIONS
