"""A site's custom block may set what the template sets once (box .120,
2026-10-26): with "client_max_body_size 50m;" there, every rewrite of the
vhost failed nginx -t as a duplicate, and with it every update's site
refresh. The custom value wins; and one site nginx refuses no longer stops
an update halfway."""
from pathlib import Path

import pytest

from app.services import nginx

UPDATE = (Path(__file__).resolve().parents[3] / "installer" / "update.sh").read_text(encoding="utf-8")
ROOT = "/home/bp_example_test/example.test"


def _primary(rendered: str) -> str:
    """The first server block: the one that serves."""
    return rendered.split("\n}\n", 1)[0]


@pytest.mark.parametrize("custom, expected", [
    ("client_max_body_size 50m;\n", {"client_max_body_size"}),
    ("# a note\nclient_max_body_size 50m; # and why\n", {"client_max_body_size"}),
    ("location /upload { client_max_body_size 2g; }\n", set()),
    ("location /upload {\n    client_max_body_size 2g;\n}\nexpires 1h;\n", {"expires"}),
    ("", set()),
])
def test_only_what_the_server_block_itself_sets_counts(custom, expected):
    assert nginx._custom_top_level_directives(custom) == expected


@pytest.mark.parametrize("app_type, kwargs", [
    ("wordpress", {"php_version": "8.3"}),
    ("php", {"php_version": "8.3"}),
    ("static", {}),
    ("application", {"app_port": 21000}),
])
def test_the_custom_value_wins_over_the_templates(app_type, kwargs):
    plain = _primary(nginx.render_vhost("example.test", ROOT, app_type=app_type, **kwargs))
    assert plain.count("    client_max_body_size 1100M;") == 1
    custom = _primary(nginx.render_vhost("example.test", ROOT, app_type=app_type,
                                         custom_directives="client_max_body_size 50m;\n", **kwargs))
    assert "client_max_body_size" not in custom, "the template's line would duplicate the custom one"
    assert "include /etc/nginx/bpanel/custom/example.test.conf;" in custom
    # Set inside a location of its own, it is not a duplicate: the default stays.
    nested = _primary(nginx.render_vhost("example.test", ROOT, app_type=app_type,
                                         custom_directives="location /upload {\n    client_max_body_size 2g;\n}\n", **kwargs))
    assert nested.count("    client_max_body_size 1100M;") == 1


def test_saving_the_custom_block_alone_takes_the_line_out_and_puts_it_back():
    vhost = nginx.render_vhost("example.test", ROOT, app_type="php", php_version="8.3")
    without = nginx._apply_custom_overrides(vhost, "client_max_body_size 50m;")
    assert "client_max_body_size" not in _primary(without)
    back = nginx._apply_custom_overrides(without, "")
    assert _primary(back).count("    client_max_body_size 1100M;") == 1
    assert nginx._apply_custom_overrides(back, "") == back, "nothing to do the second time"


def test_one_site_nginx_refuses_does_not_stop_the_update():
    refresh = UPDATE[UPDATE.index('log "Refreshing managed site configuration"'):]
    refresh = refresh[:refresh.index("\nPY\n")]
    assert "    def refresh_site(website):" in refresh
    batch = refresh[refresh.index("        with nginx.deferred_reload():"):]
    assert "except Exception as exc:" in batch and "refreshing the sites one by one" in batch
    assert batch.count("refresh_site(website)") == 2, "the batch, then site by site"
    # The last reload is not what fails a finished update either.
    tail = UPDATE[UPDATE.index('log "Reloading nginx"'):]
    tail = tail[:tail.index("# --- Did turning HTTPS on actually work?")]
    assert "if nginx -t; then\n  systemctl reload nginx\nelse" in tail
    assert "\nnginx -t\nsystemctl reload nginx\n" not in tail
