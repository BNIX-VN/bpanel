"""A custom block may turn a location's access log off and set the security,
CORS and robots headers (operator, 2026-11-09: an Astro site's block with
`access_log off;` and X-Content-Type-Options was refused). Logging to a path,
Set-Cookie and Location stay refused."""
import pytest

from app.services import nginx

ASTRO = '''    location /_astro/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        add_header X-Content-Type-Options "nosniff" always;
        try_files $uri =404;
    }
    location /images/ {
        add_header Cache-Control "public, max-age=2592000";
        add_header X-Content-Type-Options "nosniff" always;
        try_files $uri =404;
    }

    # Giảm log rác
    location = /favicon.png { log_not_found off; access_log off; }
    location = /robots.txt  { log_not_found off; access_log off; }
'''


def test_the_operators_block_is_accepted():
    assert nginx.validate_custom_nginx(ASTRO)


@pytest.mark.parametrize("custom", [
    "access_log off;",
    "location /x { access_log off ; }",
    'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
    'add_header Strict-Transport-Security "max-age=31536000" always;',
    'location /api/ { add_header Access-Control-Allow-Origin "*"; }',
    'add_header X-Robots-Tag "noindex";',
])
def test_accepted(custom):
    assert nginx.validate_custom_nginx(custom)


@pytest.mark.parametrize("custom, message", [
    ("access_log /home/x/evil.log;", "disallowed directives"),
    ("location / { access_log /tmp/x combined; }", "disallowed directives"),
    ("access_log offsite.log;", "disallowed directives"),
    ("error_log off;", "disallowed directives"),
    ('add_header Set-Cookie "a=b; Domain=.panel.test";', "may only set"),
    ('add_header Location "https://evil.example";', "may only set"),
])
def test_refused(custom, message):
    with pytest.raises(ValueError, match=message):
        nginx.validate_custom_nginx(custom)
