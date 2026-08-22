"""The IPv6 switch: off unless somebody turns it on, and only where it can work."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services import nginx, panel_ipv6

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER_SCRIPT = PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh"
UPDATE_SCRIPT = PROJECT_ROOT / "installer" / "update.sh"


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def helper(monkeypatch):
    """Stand in for the helper, recording what the panel asked it to do."""
    calls: list[str] = []
    replies: dict[str, _Result] = {}

    def fake(command, **kwargs):
        calls.append(command)
        return replies.get(command, _Result())

    monkeypatch.setattr(panel_ipv6.shell, "privileged", fake)
    return calls, replies


def test_status_reads_what_the_server_reports(helper):
    calls, replies = helper
    replies["ipv6-status"] = _Result(
        stdout="available=yes\nenabled=yes\naddresses=2001:db8::1,2001:db8::2\n"
    )

    state = panel_ipv6.status()

    assert calls == ["ipv6-status"]
    assert state["available"] is True
    assert state["enabled"] is True
    assert state["addresses"] == ["2001:db8::1", "2001:db8::2"]


def test_a_server_without_ipv6_says_so(helper):
    _, replies = helper
    replies["ipv6-status"] = _Result(stdout="available=no\nenabled=no\naddresses=\n")

    state = panel_ipv6.status()

    assert state == {
        "available": False,
        "enabled": False,
        "addresses": [],
        "detail": panel_ipv6.NO_IPV6_MESSAGE,
    }


def test_enabling_is_refused_when_the_server_has_no_ipv6(helper):
    calls, replies = helper
    replies["ipv6-status"] = _Result(stdout="available=no\nenabled=no\naddresses=\n")

    with pytest.raises(HTTPException) as raised:
        panel_ipv6.set_enabled(True)

    assert raised.value.status_code == 400
    assert "không có địa chỉ IPv6" in raised.value.detail
    # Refused before the helper was ever asked to change anything.
    assert "ipv6-enable" not in calls


def test_enabling_asks_the_helper_when_the_server_has_ipv6(helper):
    calls, replies = helper
    replies["ipv6-status"] = _Result(stdout="available=yes\nenabled=yes\naddresses=2001:db8::1\n")

    state = panel_ipv6.set_enabled(True)

    assert "ipv6-enable" in calls
    assert state["enabled"] is True
    assert state["message"]


def test_a_helper_failure_becomes_a_readable_error(helper):
    _, replies = helper
    replies["ipv6-status"] = _Result(stdout="available=yes\nenabled=no\naddresses=2001:db8::1\n")
    replies["ipv6-enable"] = _Result(
        returncode=1, stderr="nginx refused the IPv6 configuration; nothing was changed"
    )

    with pytest.raises(HTTPException) as raised:
        panel_ipv6.set_enabled(True)

    assert "nginx refused" in raised.value.detail


def test_turning_it_off_never_needs_ipv6_to_be_present(helper):
    calls, replies = helper
    replies["ipv6-status"] = _Result(stdout="available=no\nenabled=no\naddresses=\n")

    panel_ipv6.set_enabled(False)

    assert "ipv6-disable" in calls


def test_the_marker_file_is_what_says_it_is_on(monkeypatch, tmp_path):
    marker = tmp_path / "ipv6-enabled"
    monkeypatch.setattr(panel_ipv6, "MARKER", marker)
    assert panel_ipv6.is_enabled() is False
    marker.write_text("", encoding="utf-8")
    assert panel_ipv6.is_enabled() is True


@pytest.mark.parametrize("app_type", ["wordpress", "php", "static"])
def test_a_new_website_listens_on_ipv6_only_when_the_switch_is_on(monkeypatch, app_type):
    monkeypatch.setattr(nginx.panel_ipv6, "is_enabled", lambda: False)
    off = nginx.render_vhost("example.test", "/home/bp_example/example.test", app_type=app_type)
    assert "listen 80;" in off
    assert "listen [::]:80;" not in off

    monkeypatch.setattr(nginx.panel_ipv6, "is_enabled", lambda: True)
    on = nginx.render_vhost("example.test", "/home/bp_example/example.test", app_type=app_type)
    assert "listen 80;" in on
    assert "listen [::]:80;" in on


def test_the_helper_checks_the_server_before_turning_it_on():
    helper_text = HELPER_SCRIPT.read_text(encoding="utf-8")
    assert "ipv6-enable)" in helper_text
    assert "ipv6_available || deny" in helper_text
    # A global address only: loopback and link-local carry nothing from outside.
    assert "ip -6 -o addr show scope global" in helper_text


def test_the_helper_puts_every_file_back_if_nginx_refuses():
    helper_text = HELPER_SCRIPT.read_text(encoding="utf-8")
    body = helper_text.split("nginx_ipv6_apply() {", 1)[1].split("\n}", 1)[0]
    assert 'cp -a "$file" "${backup}/$(basename "$file")"' in body
    assert "nginx -t" in body
    assert 'cp -a "$file" "/etc/nginx/conf.d/$(basename "$file")"' in body
    assert "return 1" in body
    # And the marker goes away again, so the switch never claims to be on.
    assert '''      rm -f "$PANEL_IPV6_MARKER"''' in helper_text


def test_certbot_https_lines_get_an_ipv6_twin():
    helper_text = HELPER_SCRIPT.read_text(encoding="utf-8")
    # certbot writes 'listen 443 ssl; # managed by Certbot'. Without the
    # trailing comment in the pattern every HTTPS vhost would be skipped.
    assert r'listen\s+((?:\d{1,3}\.){3}\d{1,3}:)?(\d+)([^;]*);\s*(#.*)?$' in helper_text


def test_an_update_re_applies_the_switch():
    update = UPDATE_SCRIPT.read_text(encoding="utf-8")
    assert "/usr/local/sbin/bpanel-helper ipv6-apply" in update


def test_the_switch_turns_itself_off_if_the_address_disappears():
    helper_text = HELPER_SCRIPT.read_text(encoding="utf-8")
    block = helper_text.split("ipv6-apply)", 1)[1].split(";;", 1)[0]
    assert "ipv6_is_enabled && ! ipv6_available" in block
    assert 'rm -f "$PANEL_IPV6_MARKER"' in block
