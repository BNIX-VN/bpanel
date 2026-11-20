"""On an IPv6 box an HTTPS site listens on [::]:443, not [::]:80 (1.20.3).

The templates write `listen [::]:80;` beside `listen 80;`, and the SSL step
turned only `listen 80;` into 443. The HTTPS server kept `listen [::]:80;`:
IPv6 visitors got the site over plain HTTP with no redirect, IPv6 HTTPS did
not answer, and the redirect servers had no IPv6 line - until the helper's
ipv6-apply pass happened to run (an update, the IPv6 switch, a mail install).
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import nginx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
ROOT = "/home/bp_example/example.test"
CERT = "/etc/nginx/bpanel/ssl/sites/example.test/cert.pem"
KEY = "/etc/nginx/bpanel/ssl/sites/example.test/key.pem"

CERTBOT_VHOST = """server {
    listen 80;
    server_name example.test www.example.test;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    server_name example.test www.example.test;
    ssl_certificate /etc/letsencrypt/live/example.test/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/example.test/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
    root /home/bp_example/example.test/public_html;
}
"""


def _servers(content: str) -> list[str]:
    return ["server {" + part for part in content.split("server {")[1:]]


def _listens(block: str) -> list[str]:
    return [line.strip() for line in block.splitlines() if line.strip().startswith("listen ")]


def _https_and_redirects(content: str):
    servers = _servers(content)
    https = [s for s in servers if "ssl_certificate " in s]
    redirects = [s for s in servers if "return 301 https://" in s and "ssl_certificate " not in s]
    return https, redirects


@pytest.fixture
def ipv6(monkeypatch):
    def switch(on: bool):
        monkeypatch.setattr(nginx.panel_ipv6, "is_enabled", lambda: on)
    return switch


@pytest.mark.parametrize("app_type", ["wordpress", "php", "static"])
def test_an_https_site_listens_on_ipv6_443_and_redirects_on_ipv6_80(ipv6, app_type):
    ipv6(True)
    content = nginx.render_vhost("example.test", ROOT, app_type=app_type, ssl_cert_path=CERT, ssl_key_path=KEY)
    https, redirects = _https_and_redirects(content)
    assert len(https) == 1 and redirects
    assert _listens(https[0]) == ["listen 443 ssl http2;", "listen [::]:443 ssl http2;"]
    for block in redirects:
        assert _listens(block) == ["listen 80;", "listen [::]:80;"]
    assert "listen [::]:80;" not in https[0]


def test_with_ipv6_off_there_is_no_ipv6_line_at_all(ipv6):
    ipv6(False)
    content = nginx.render_vhost("example.test", ROOT, app_type="wordpress", ssl_cert_path=CERT, ssl_key_path=KEY)
    assert "[::]" not in content


def test_redirect_domains_get_their_twins_too(ipv6):
    ipv6(True)
    content = nginx.render_vhost("example.test", ROOT, app_type="wordpress", ssl_cert_path=CERT, ssl_key_path=KEY,
                                 redirects=["old.example.test"])
    for block in _servers(content):
        v4 = [line for line in _listens(block) if not line.startswith("listen [::]")]
        v6 = [line for line in _listens(block) if line.startswith("listen [::]")]
        assert [line.replace("listen ", "listen [::]:", 1) for line in v4] == v6, block


def test_a_letsencrypt_site_rewritten_by_the_panel_listens_on_ipv6_443(ipv6, tmp_path, monkeypatch):
    # The certbot path: the panel re-renders, then merges certbot's lines from
    # the live vhost - the step that left [::]:80 in the HTTPS server.
    ipv6(True)
    vhost = tmp_path / "example.test.conf"
    vhost.write_text(CERTBOT_VHOST, encoding="utf-8")
    monkeypatch.setattr(nginx.settings, "command_dry_run", False)
    monkeypatch.setattr(nginx.settings, "nginx_sites_available", str(tmp_path))
    monkeypatch.setattr(nginx, "_vhost_path", lambda d: vhost)
    monkeypatch.setattr(nginx, "_custom_include_snapshot", lambda d: None)
    monkeypatch.setattr(nginx, "_write_custom_include", lambda d, c: None)
    monkeypatch.setattr(nginx, "_write_backup", lambda t, c: None)
    monkeypatch.setattr(nginx, "_test_and_reload", lambda *a, **k: None)
    nginx.rewrite_vhost("example.test", ROOT, app_type="wordpress", php_version="8.3", blocked_bots=[], fastcgi_cache=True)
    written = vhost.read_text(encoding="utf-8")
    https, redirects = _https_and_redirects(written)
    assert len(https) == 1 and "managed by Certbot" in https[0]
    assert _listens(https[0]) == ["listen 443 ssl http2;", "listen [::]:443 ssl http2;"]
    for block in redirects:
        assert _listens(block) == ["listen 80;", "listen [::]:80;"]


def test_twins_are_idempotent_and_pinned_addresses_are_left_alone(ipv6):
    ipv6(True)
    once = nginx._ipv6_listen_twins("server {\n    listen 443 ssl; # managed by Certbot\n"
                                    "    listen 10.0.0.5:8080;\n}\n")
    assert once == ("server {\n    listen 443 ssl; # managed by Certbot\n    listen [::]:443 ssl;\n"
                    "    listen 10.0.0.5:8080;\n}\n")
    assert nginx._ipv6_listen_twins(once) == once


def _helper_rewrite(conf_dir: Path, mode: str) -> None:
    script = HELPER.split("python3 - \"$mode\" <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    assert '"/etc/nginx/conf.d/*.conf"' in script
    script = script.replace('"/etc/nginx/conf.d/*.conf"', repr(conf_dir.as_posix() + "/*.conf"))
    subprocess.run([sys.executable, "-c", script, mode], check=True, capture_output=True)


@pytest.mark.parametrize("redirects", [None, ["old.example.test"]])
def test_the_helpers_ipv6_pass_finds_nothing_left_to_change(ipv6, tmp_path, redirects):
    # Same rule in both places: an update's ipv6-apply after a panel write is
    # a no-op, and turning the switch off still removes every IPv6 line.
    ipv6(True)
    content = nginx.render_vhost("example.test", ROOT, app_type="wordpress", ssl_cert_path=CERT, ssl_key_path=KEY,
                                 redirects=redirects)
    conf = tmp_path / "example.test.conf"
    conf.write_text(content, encoding="utf-8", newline="\n")
    _helper_rewrite(tmp_path, "on")
    assert conf.read_text(encoding="utf-8") == content
    _helper_rewrite(tmp_path, "off")
    ipv6(False)
    off = nginx.render_vhost("example.test", ROOT, app_type="wordpress", ssl_cert_path=CERT, ssl_key_path=KEY,
                             redirects=redirects)
    assert conf.read_text(encoding="utf-8") == off
    assert not re.search(r"listen \[::\]", off)
