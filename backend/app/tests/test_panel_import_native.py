"""Another OPanel or BPanel server as a migration source (feat/panel-import).

Signed in to as root, it lists its accounts with <panel>ctl list-accounts and
packs one with backup-account, which prints a native .tar.gz path. The archive
restores here with backup.restore_user_backup, so it is listed and restored as
this panel's own kind -- cross-panel included.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import migrate_ssh, restore_sources


class _NativeServer:
    def __init__(self, panel, list_out="", pack_out=""):
        self.panel, self.list_out, self.pack_out = panel, list_out, pack_out
        self.commands, self.removed, self.downloaded = [], [], None

    def run(self, client, command, timeout):
        self.commands.append(command)
        if "list-accounts" in command:
            return 0, self.list_out, ""
        if "backup-account" in command:
            return 0, self.pack_out, ""
        if command.startswith("rm -f -- "):
            self.removed.append(command)
            return 0, "", ""
        raise AssertionError(command)

    def open_sftp(self):
        server = self

        class Sftp:
            def stat(self, path):
                return SimpleNamespace(st_size=4321)

            def get(self, remote, local, callback=None):
                server.downloaded = remote
                Path(local).write_bytes(b"nativearchive")
                if callback:
                    callback(4321, 4321)

            def close(self):
                pass

        return Sftp()

    def link(self):
        return migrate_ssh.Link(client=SimpleNamespace(open_sftp=self.open_sftp))


def _stage(tmp_path):
    def stage(name, pull):
        destination = tmp_path / name
        pull(str(destination))
        return str(destination)
    return stage


@pytest.mark.parametrize("panel", ["opanel", "bpanel", "bnix"])
def test_opanel_bpanel_account_list_is_read(panel):
    rows = migrate_ssh.parse_panel_accounts("bob\tbob.com\t1048576\t2\nsue\tsue.net\t0\t1\n", panel)
    assert [row["key"] for row in rows] == ["bob", "sue"]
    assert rows[0]["kind"] == migrate_ssh.NATIVE_KIND == "bpanel"
    assert rows[0]["domain"] == "bob.com" and rows[0]["size"] == 1048576 and rows[0]["note"] == "2 sites"
    assert rows[1]["size"] == 0 and rows[1]["note"] == ""
    with pytest.raises(migrate_ssh.MigrateError, match="up to date"):
        migrate_ssh.parse_panel_accounts(migrate_ssh.PANEL_MISSING[panel] + "\n", panel)


@pytest.mark.parametrize("panel", ["opanel", "bpanel", "bnix"])
def test_list_accounts_dispatches_to_the_native_cli(panel, monkeypatch):
    server = _NativeServer(panel, list_out="bob\tbob.com\t10\t1\n")
    monkeypatch.setattr(migrate_ssh, "_exec", lambda c, cmd, t: server.run(c, cmd, t))
    rows = migrate_ssh.list_accounts(SimpleNamespace(), panel)
    assert rows[0]["key"] == "bob" and rows[0]["kind"] == migrate_ssh.NATIVE_KIND
    assert any("list-accounts" in c for c in server.commands)


@pytest.mark.parametrize("panel", ["opanel", "bpanel", "bnix"])
def test_native_account_is_packed_downloaded_and_removed(tmp_path, monkeypatch, panel):
    path = "/home/bob/backups/bob-manual-tuesday.tar.gz"
    server = _NativeServer(panel, pack_out=path + "\n")
    monkeypatch.setattr(migrate_ssh, "_exec", lambda c, cmd, t: server.run(c, cmd, t))
    got = migrate_ssh.pack_and_fetch(server.link(), panel, "bob", _stage(tmp_path), lambda size: None)
    assert Path(got) == tmp_path / "bob-manual-tuesday.tar.gz"
    assert Path(got).read_bytes() == b"nativearchive"
    assert server.downloaded == path
    assert server.removed == [f"rm -f -- {path}"]
    assert any("backup-account bob" in c for c in server.commands)


def test_native_pack_refuses_a_non_archive_path_and_removes_nothing(tmp_path, monkeypatch):
    server = _NativeServer("opanel", pack_out="/etc/passwd\n")
    monkeypatch.setattr(migrate_ssh, "_exec", lambda c, cmd, t: server.run(c, cmd, t))
    with pytest.raises(migrate_ssh.MigrateError, match="no archive"):
        migrate_ssh.pack_and_fetch(server.link(), "opanel", "bob", _stage(tmp_path), lambda size: None)
    assert server.removed == []


def test_key_kind_treats_a_native_source_as_this_panels_kind():
    for panel in ("opanel", "bpanel"):
        assert restore_sources.key_kind({"kind": "ssh", "panel": panel}, "bob") == restore_sources.KIND_PANEL
    # A foreign source keeps its own kind.
    assert restore_sources.key_kind({"kind": "ssh", "panel": "cpanel"}, "bob") == "cpanel"


def test_bnix_source_probes_both_panel_clis():
    # The auto-detecting "bnix" source tries both OPanel's and BPanel's CLI names,
    # so whichever the old server runs answers -- the operator need not know.
    cmd = migrate_ssh._panelctl_cmd("bnix", "list-accounts")
    for name in ("opanelctl", "bpanelctl", "opanel", "bpanel"):
        assert name in cmd
    assert "bnix" in migrate_ssh.NATIVE_PANELS
