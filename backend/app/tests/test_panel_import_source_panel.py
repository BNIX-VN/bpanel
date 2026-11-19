"""OPanel/BPanel Import: an account is packed by the panel the OTHER server runs
(2026-11-19).

An OPanel or BPanel account becomes kind "bpanel" here whichever panel made it,
and the fetch handed that kind to the packer as if it were the source panel - so
it only ever looked for bpanelctl, and an account on an OPanel server never came
across ("left no archive (NO_BPANEL_CLI)"), in 1.20.0 with OPanel picked and in
1.20.1 with the auto-detecting "bnix" source alike. Found by a real import from
an OPanel box; the packer itself was tested per panel, the wiring was not.
"""
from contextlib import contextmanager

import pytest

from app.services import migrate_ssh, restore_sources


@pytest.mark.parametrize("panel", ["bnix", "opanel", "bpanel"])
def test_the_account_is_packed_by_the_panel_the_other_server_runs(monkeypatch, tmp_path, panel):
    seen = {}

    @contextmanager
    def fake_ssh(source, pinned=""):
        yield object(), {"type": "ssh-ed25519", "fingerprint": pinned}

    def pack(link, source_panel, account, stage, ensure_room, on_status=None, on_progress=None, size_hint=0):
        seen["panel"] = source_panel
        return str(tmp_path / f"user-{account}-20261119000000.tar.gz")

    monkeypatch.setattr(restore_sources, "_ssh", fake_ssh)
    monkeypatch.setattr(restore_sources, "_ensure_foreign_dir", lambda kind: None)
    monkeypatch.setattr(restore_sources, "foreign_dir", lambda kind: tmp_path)
    monkeypatch.setattr(restore_sources.migrate_ssh, "pack_and_fetch", pack)
    source = {"kind": "ssh", "panel": panel, "host": "203.0.113.7", "password": "pw", "host_key": "SHA256:k"}

    restore_sources.fetch(source, "bob", 0, db=None)

    assert restore_sources.key_kind(source, "bob") == restore_sources.KIND_PANEL
    assert seen["panel"] == panel, "packed by the source's panel, not by this side's archive kind"


def test_the_auto_detecting_source_tries_both_panels_clis():
    command = migrate_ssh._panelctl_cmd("bnix", "backup-account bob")
    assert "opanelctl" in command and "bpanelctl" in command
    assert command.rstrip().endswith("echo NO_BNIX_CLI")


def _pull_with(monkeypatch, tmp_path, panel, archive_name):
    """Run fetch() over SSH with a packer that hands back ``archive_name``."""
    monkeypatch.setattr(restore_sources.settings, "backup_root", str(tmp_path / "backups"))
    monkeypatch.setattr(restore_sources.backup, "_ensure_user_dir",
                        lambda path: (path.mkdir(parents=True, exist_ok=True), path)[1])
    da_folder = tmp_path / "da"
    da_folder.mkdir()
    monkeypatch.setattr(restore_sources, "_ensure_foreign_dir", lambda kind: None)
    monkeypatch.setattr(restore_sources, "foreign_dir", lambda kind: da_folder)

    @contextmanager
    def fake_ssh(source, pinned=""):
        yield object(), {"type": "ssh-ed25519", "fingerprint": pinned}

    def pack(link, source_panel, account, stage, ensure_room, on_status=None, on_progress=None, size_hint=0):
        return stage(archive_name, lambda destination: open(destination, "wb").write(b"archive"))

    monkeypatch.setattr(restore_sources, "_ssh", fake_ssh)
    monkeypatch.setattr(restore_sources.migrate_ssh, "pack_and_fetch", pack)
    source = {"kind": "ssh", "panel": panel, "host": "203.0.113.7", "password": "pw", "host_key": "SHA256:k"}
    path, is_copy = restore_sources.fetch(source, "bob", 0, db=None)
    return path, is_copy, da_folder


def test_an_opanel_or_bpanel_account_lands_where_the_restore_reads(monkeypatch, tmp_path):
    # OPanel names its archives "<user>-manual-<day>.tar.gz"; BPanel "user-<user>-<stamp>.tar.gz".
    path, is_copy, da_folder = _pull_with(monkeypatch, tmp_path, "bnix", "bob-manual-thursday.tar.gz")
    assert is_copy
    assert restore_sources.backup.user_backup_path(path), "the restore accepts it (it said 'Backup not found')"
    assert str(path).startswith(str(restore_sources.backup.user_restore_dir()))
    assert list(da_folder.iterdir()) == [], "not in the DirectAdmin import's folder"


def test_a_directadmin_account_still_lands_in_its_import_folder(monkeypatch, tmp_path):
    path, is_copy, da_folder = _pull_with(monkeypatch, tmp_path, "directadmin", "user.admin.bob.tar.zst")
    assert is_copy and str(path).startswith(str(da_folder))
