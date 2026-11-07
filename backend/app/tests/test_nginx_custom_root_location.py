"""A custom block may say `location / { return 403; }` (operator, 2026-11-08).

Refused twice before: `return` was on the deny-list, and the template's own
`location / { try_files ... }` made a second one a duplicate nginx rejects. A
status or an on-site redirect is allowed now, never a body or another address;
and while the custom block sets location /, the template's is commented out,
coming back as it was when the custom block stops setting it.
"""
import pytest

from app.services import nginx

ROOT = "/home/bp_example_test/example.test"
OPERATOR = "location / {\n    return 403;\n}\n\nlocation /wp-admin/ {\n    try_files $uri $uri/ /index.php?$args;\n}\n"


def _primary(rendered: str) -> str:
    return rendered.split("\n}\n", 1)[0]


@pytest.mark.parametrize("custom", [
    OPERATOR,
    "location ~ /\\.git { return 404; }",
    "location /old { return 301 /new$request_uri; }",
    "if ($scheme = http) { return 301 https://$host$request_uri; }",
    "location /x { deny all; return 444; }",
])
def test_a_status_or_an_on_site_redirect_is_accepted(custom):
    assert nginx.validate_custom_nginx(custom)


@pytest.mark.parametrize("custom, message", [
    ('location / { return 200 "<h1>pay here</h1>"; }', "quoted"),
    ("location / { return 200 hello; }", "status code"),
    ("location / { return 302 https://evil.example/; }", "stay on the site"),
    ("location / { return 302 //evil.example/; }", "stay on the site"),
    ("location / { return 301 https://$host.evil.example/; }", "stay on the site"),
    ("location / { return 301; }", "stay on the site"),
    ("location / { return 999; }", "between 200 and 599"),
    ("location / { return $foo; }", "Malformed"),
])
def test_a_body_or_another_address_is_refused(custom, message):
    with pytest.raises(ValueError, match=message):
        nginx.validate_custom_nginx(custom)


@pytest.mark.parametrize("custom, expected", [
    (OPERATOR, True),
    ("location / { deny all; }", True),
    ("location /wp-admin/ { deny all; }", False),
    ("location = / { return 404; }", False),
    ("location /a { location / { deny all; } }", False),
    ("# location / { }\n", False),
])
def test_only_a_top_level_location_slash_counts(custom, expected):
    assert nginx._custom_sets_root_location(custom) is expected


@pytest.mark.parametrize("app_type", ["php", "wordpress", "static"])
def test_the_templates_location_slash_steps_aside_and_comes_back(app_type):
    vhost = nginx.render_vhost("example.test", ROOT, app_type=app_type, php_version="8.3")
    assert _primary(vhost).count("\n    location / {\n") == 1
    custom = nginx.render_vhost("example.test", ROOT, app_type=app_type, php_version="8.3", custom_directives=OPERATOR)
    assert "\n    location / {\n" not in _primary(custom)
    assert nginx.ROOT_LOCATION_OFF in custom and "    #~location / {\n" in custom
    # Saving the block alone (update_custom_block) does the same, and undoes it.
    off = nginx._apply_custom_overrides(vhost, OPERATOR)
    assert off == custom or "\n    location / {\n" not in _primary(off)
    assert nginx._apply_custom_overrides(off, OPERATOR) == off, "nothing to do the second time"
    assert nginx._apply_custom_overrides(off, "") == vhost


def test_a_proxys_location_slash_is_never_taken_out():
    vhost = nginx.render_vhost("example.test", ROOT, app_type="application", app_port=21000)
    assert nginx._apply_custom_overrides(vhost, OPERATOR) == vhost
