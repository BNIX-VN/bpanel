from app.services import nginx


def test_wordpress_csp_allows_gutenberg_blob_iframe():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="wordpress",
        php_version="8.3",
    )

    assert "frame-src 'self' https: blob:;" in rendered


def test_php_vhost_defaults_to_static_try_files():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
    )

    assert "try_files $uri $uri/ =404;" in rendered
    assert "try_files $uri $uri/ /index.php?$query_string;" not in rendered


def test_vhost_includes_alias_domains_in_server_name():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        aliases=["alias.test", "www.example.test", "alias.test"],
    )

    assert "server_name example.test www.example.test alias.test;" in rendered


def test_vhost_renders_redirect_domains_as_separate_301_servers():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        aliases=["app-alias.test"],
        redirects=["old.example.test"],
    )

    assert "server_name example.test www.example.test app-alias.test;" in rendered
    assert "server_name old.example.test;" in rendered
    assert "location ^~ /.well-known/acme-challenge/ {" in rendered
    assert "root /var/www/bpanel-acme;" in rendered
    assert "return 301 https://example.test$request_uri;" in rendered


def test_manual_ssl_vhost_adds_https_redirect_server_for_redirect_domains():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        redirects=["old.example.test"],
        ssl_cert_path="/etc/nginx/bpanel/ssl/sites/example.test/cert.crt",
        ssl_key_path="/etc/nginx/bpanel/ssl/sites/example.test/privkey.key",
    )

    assert "listen 443 ssl http2;" in rendered
    assert "server_name old.example.test;" in rendered
    assert "location ^~ /.well-known/acme-challenge/ {" in rendered
    assert "root /var/www/bpanel-acme;" in rendered
    assert "ssl_certificate /etc/nginx/bpanel/ssl/sites/example.test/cert.crt;" in rendered
    assert "return 301 https://example.test$request_uri;" in rendered


def test_php_vhost_supports_front_controller_rewrite_mode():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        rewrite_mode="front_controller",
    )

    assert "try_files $uri $uri/ /index.php?$query_string;" in rendered


def test_php_vhost_supports_laravel_rewrite_mode_without_changing_root():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        rewrite_mode="laravel",
    )

    root_line = next(line.strip() for line in rendered.splitlines() if line.strip().startswith("root "))
    assert root_line.replace("\\", "/").endswith("public_html/public;")
    assert "try_files $uri $uri/ /index.php?$query_string;" in rendered


def test_php_vhost_laravel_rewrite_mode_does_not_double_public_root():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        document_root="public_html/public",
        rewrite_mode="laravel",
    )

    root_line = next(line.strip() for line in rendered.splitlines() if line.strip().startswith("root "))
    normalized = root_line.replace("\\", "/")
    assert normalized.endswith("public_html/public;")
    assert "public_html/public/public" not in normalized


def test_php_vhost_supports_codeigniter_rewrite_mode():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        rewrite_mode="codeigniter",
    )

    assert "try_files $uri $uri/ /index.php?$query_string;" in rendered


def test_php_vhost_supports_seohburl_rewrite_mode():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="php",
        php_version="8.3",
        rewrite_mode="seohburl",
    )

    assert "try_files $uri $uri/ @seohburl;" in rendered
    assert "location @seohburl" in rendered
    assert "rewrite ^/(.+)$ /index.php?/$1 last;" in rendered


def test_ensure_hsts_header_adds_gutenberg_safe_wordpress_csp():
    content = '\n'.join([
        "server {",
        "    server_tokens off;",
        '    add_header X-XSS-Protection "1; mode=block" always;',
        "}",
        "",
    ])

    hardened = nginx._ensure_hsts_header(content)

    assert "frame-src 'self' https: blob:;" in hardened
