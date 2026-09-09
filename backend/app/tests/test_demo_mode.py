"""Demo mode: a place to look, not a place to act."""

import pytest

from app.core import demo


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(demo.settings, "demo_mode", True)


def test_off_by_default_blocks_nothing(monkeypatch):
    monkeypatch.setattr(demo.settings, "demo_mode", False)
    assert demo.blocks("DELETE", "/api/websites/1") is False
    assert demo.blocks("POST", "/api/terminal/exec/1") is False


def test_reading_is_the_whole_point(demo_on):
    # A demo that cannot show the panel is not a demo.
    for path in [
        "/api/websites",
        "/api/users",
        "/api/databases",
        "/api/services/list",
        "/api/services/system-info",
        "/api/waf/rules",
        "/api/waf/status",
        "/api/firewall/status",
        "/api/malware/status",
        "/api/packages",
        "/api/panel-settings",
        "/api/updates/status",
        "/api/websites/1/logs",
    ]:
        assert demo.blocks("GET", path) is False, f"a demo visitor should be able to read {path}"


def test_nothing_can_be_changed(demo_on):
    for method, path in [
        ("POST", "/api/websites"),
        ("DELETE", "/api/websites/1"),
        ("PATCH", "/api/websites/1/waf"),
        ("PUT", "/api/waf/bots/global"),
        ("POST", "/api/users"),
        ("DELETE", "/api/users/2"),
        ("POST", "/api/firewall/allow-ip"),
        ("POST", "/api/maintenance/wordpress"),
        ("POST", "/api/malware/run"),
        ("PATCH", "/api/panel-settings"),
        ("POST", "/api/updates/run"),
        ("POST", "/api/provisioning/v1/tokens"),
    ]:
        assert demo.blocks(method, path) is True, f"{method} {path} should be refused"


def test_the_login_flow_still_works(demo_on):
    """Otherwise the demo cannot be entered at all."""
    assert demo.blocks("POST", "/api/auth/login") is False
    assert demo.blocks("POST", "/api/auth/logout") is False


def test_two_factor_cannot_be_changed_on_a_shared_account(demo_on):
    """A demo account is handed to strangers. The first visitor to enable 2FA
    would lock out everyone after them, including the operator."""
    assert demo.blocks("POST", "/api/auth/2fa/enable") is True
    assert demo.blocks("POST", "/api/auth/2fa/disable") is True
    assert demo.blocks("POST", "/api/auth/2fa/setup") is True


def test_downloads_are_refused_even_though_they_are_gets(demo_on):
    """Reads by HTTP method, exfiltration by effect - and a bandwidth bill on a
    public server."""
    for path in [
        "/api/databases/1/download",
        "/api/maintenance/backups/1/download",
        "/api/maintenance/user-backups-download",
        "/api/maintenance/files/1/download",
        "/api/maintenance/files/1/read",
        "/api/maintenance/app-files/1/read",
    ]:
        assert demo.blocks("GET", path) is True, f"{path} hands data out and should be refused"


def test_phpmyadmin_sso_is_a_door_out_of_the_panel(demo_on):
    """It consumes a token and lands the visitor in phpMyAdmin with real
    database access. Nothing past that point is the panel's to control."""
    assert demo.blocks("GET", "/api/databases/phpmyadmin-sso/sometoken") is True


def test_the_terminal_is_refused_by_any_route(demo_on):
    assert demo.blocks("POST", "/api/terminal/exec/1") is True
    assert demo.blocks("GET", "/api/terminal/allowed-commands") is True
    # The websocket never reaches HTTP middleware, so terminal.py checks
    # demo.enabled() itself - asserted below against the real source.


def test_the_websocket_checks_demo_mode_itself():
    from pathlib import Path

    from app.api import terminal as terminal_api

    src = Path(terminal_api.__file__).read_text(encoding="utf-8")
    ws = src[src.index('@router.websocket'):]
    assert "demo.enabled()" in ws, (
        "the terminal websocket does not check demo mode; HTTP middleware cannot see it"
    )


def test_demo_mode_cannot_be_switched_from_inside_the_panel():
    """A demo is handed out with working credentials. If the switch were
    reachable over the API, the first visitor would turn it off."""
    from pathlib import Path

    import app.api.panel_settings as panel_settings_api

    src = Path(panel_settings_api.__file__).read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "demo_mode =" not in stripped, f"demo mode is assignable over the API: {stripped}"


def test_a_trailing_slash_does_not_get_past_the_guard(demo_on):
    assert demo.blocks("DELETE", "/api/websites/1/") is True
    assert demo.blocks("POST", "/api/terminal/exec/1/") is True
