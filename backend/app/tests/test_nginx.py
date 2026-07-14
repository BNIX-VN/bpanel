from app.services import nginx


def test_wordpress_csp_allows_gutenberg_blob_iframe():
    rendered = nginx.render_vhost(
        "example.test",
        "/home/bp_example_test/example.test",
        app_type="wordpress",
        php_version="8.3",
    )

    assert "frame-src 'self' https: blob:;" in rendered


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
