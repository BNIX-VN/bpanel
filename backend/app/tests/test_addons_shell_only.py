"""Email and Resource limits are installed from the server's shell only
(operator, 2026-11-02): the Addons page does not offer them, the API refuses
them, and `bpanel addon install <slug>` installs them to the end."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import addon_cli
from app.api import addons as addons_api
from app.services import addons

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BPANELCTL = (PROJECT_ROOT / "installer" / "files" / "bpanelctl").read_text(encoding="utf-8")
APP = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
SHELL_ONLY = (addons.MAIL, addons.LIMITS)
ADMIN = SimpleNamespace(id=1, role="admin")


class _FakeDb:
    """Enough of a session for the shell path: no administrator, nothing stored."""

    def query(self, *a):
        return self

    def filter(self, *a):
        return self

    def order_by(self, *a):
        return self

    def first(self):
        return None

    def all(self):
        return []

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path)
    monkeypatch.setattr(addons, "ADDONS_FILE", tmp_path / "addons.json")
    work: list[str] = []
    monkeypatch.setattr(addons_api, "log_action", lambda *a, **k: None)
    monkeypatch.setattr(addons_api.mail, "install", lambda: work.append("mail.install"))
    monkeypatch.setattr(addons_api.mail, "after_install", lambda db: work.append("mail.after_install"))
    monkeypatch.setattr(addons_api.mail, "stop", lambda: work.append("mail.stop"))
    monkeypatch.setattr(addons_api.resource_limits, "install", lambda: work.append("limits.install"))
    monkeypatch.setattr(addons_api.resource_limits, "sync_quietly", lambda db: work.append("limits.sync"))
    monkeypatch.setattr(addons_api.resource_limits, "uninstall", lambda: work.append("limits.uninstall"))
    import app.core.database as database

    monkeypatch.setattr(database, "SessionLocal", _FakeDb)
    return SimpleNamespace(work=work)


def _listed(role="admin"):
    return {item["slug"] for item in addons_api.list_addons(current_user=SimpleNamespace(id=1, role=role))["items"]}


def test_the_page_does_not_offer_them_until_they_are_installed(env):
    listed = _listed()
    assert not listed & set(SHELL_ONLY)
    assert addons.FAIL2BAN in listed and addons.DNS in listed   # the others are still offered
    addons.install(addons.MAIL)
    entry = next(item for item in addons_api.list_addons(current_user=ADMIN)["items"] if item["slug"] == addons.MAIL)
    # Installed from the shell, it is listed to be managed (settings, remove).
    assert entry["installed"] and entry["cli_only"]
    assert entry["install_command"] == "bpanel addon install mail"
    assert addons.LIMITS not in _listed() and addons.LIMITS not in _listed("end_user")


@pytest.mark.parametrize("slug", SHELL_ONLY)
def test_the_panel_cannot_install_them(env, slug):
    with pytest.raises(HTTPException) as caught:
        addons_api.install_addon(slug, db=None, current_user=ADMIN)
    assert caught.value.status_code == 403
    assert f"bpanel addon install {slug}" in caught.value.detail
    assert env.work == [] and not addons.is_installed(slug)


def test_a_route_of_a_missing_shell_only_addon_names_the_command(env):
    with pytest.raises(HTTPException) as caught:
        addons.require_mail()
    assert caught.value.status_code == 409 and "bpanel addon install mail" in caught.value.detail


def test_the_shell_installs_to_the_end_with_the_work_that_follows(env):
    assert addon_cli.main(["install", "mail"]) == 0
    # Installed, recorded and its mailboxes written out before the CLI exits.
    assert env.work == ["mail.install", "mail.after_install"]
    assert addons.is_installed(addons.MAIL)
    assert addon_cli.main(["install", "limits"]) == 0
    assert env.work[-2:] == ["limits.install", "limits.sync"]


def test_the_shell_reports_a_failure_and_records_nothing(env, monkeypatch):
    def failing():
        raise RuntimeError("Command failed: sudo bpanel-helper mail-install\nbpanel-helper: apt could not install exim4")

    monkeypatch.setattr(addons_api.mail, "install", failing)
    assert addon_cli.main(["install", "mail"]) == 1
    assert not addons.is_installed(addons.MAIL)


def test_the_cli(env, capsys):
    assert addon_cli.main(["install", "mail"]) == 0
    assert addon_cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "mail" in out and "installed" in out and "(shell only)" in out
    assert addon_cli.main(["install", "mail"]) == 1          # already installed
    assert addon_cli.main(["remove", "limits"]) == 1         # not installed
    assert addon_cli.main(["install", "no-such"]) == 2
    assert addon_cli.main(["frobnicate", "mail"]) == 2
    assert addon_cli.main(["remove", "mail"]) == 0
    assert "mail.stop" in env.work and not addons.is_installed(addons.MAIL)


def test_removing_from_the_page_is_still_allowed(env):
    addons.install(addons.MAIL)
    result = addons_api.uninstall_addon(addons.MAIL, db=None, current_user=ADMIN)
    assert not result["installed"] and "mail.stop" in env.work


def test_bpanel_ctl_has_the_addon_command():
    assert '  addon|--addon) addon_command "${2:-}" "${3:-}" ;;' in BPANELCTL
    # The panel's own code, as the panel user, one at a time; not `-m`, which
    # cannot run a compiled (.so) module.
    assert "from app.addon_cli import main" in BPANELCTL
    assert "runuser -u bpanel" in BPANELCTL and "flock -n" in BPANELCTL


def test_the_missing_page_shows_the_command_not_the_addons_button():
    assert "const SHELL_ONLY_ADDONS = { mail: 'Email', limits: 'Resource limits' };" in APP
    assert "bpanel addon install ${slug}" in APP
