"""OPanel/BPanel Import: an account pulled from ANOTHER server whose username is
already here is someone else's account (2026-11-19).

The import restores what it pulls with the native restore, which matches the
account by username - right for this server's own backup, wrong for another
server's: the archive's sites were added to the same-named account here and its
databases of the same name imported over that account's. Now it is refused,
before the other server even packs it, unless the operator ticks "Restore over
accounts already on this server". The page said "Overwrite" and went ahead.

The DirectAdmin/cPanel/FastPanel pulls keep their documented behaviour (an
account that exists here is overwritten with its own websites).
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import maintenance
from app.services import backup, restore_sources

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
OTHER_SERVER = {"kind": "ssh", "panel": "bnix", "host": "203.0.113.7", "port": 22, "username": "root",
                "password": "", "private_key": "KEY", "host_key": "SHA256:k"}


class _Query:
    def __init__(self, found):
        self.found = found

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.found


def _db(existing_username=None):
    found = SimpleNamespace(id=3, username=existing_username) if existing_username else None
    return SimpleNamespace(query=lambda *models: _Query(found), rollback=lambda: None, close=lambda: None,
                           get=lambda *a: None)


def test_the_restore_refuses_an_account_already_here_when_asked(monkeypatch):
    monkeypatch.setattr(backup, "user_backup_path", lambda name: Path(name))
    monkeypatch.setattr(backup, "read_backup_manifest",
                        lambda path: {"kind": "opanel_user", "user": {"username": "alice"}})
    with pytest.raises(ValueError, match="already on this server"):
        backup.restore_user_backup("user-alice.tar.gz", _db("alice"), refuse_existing_user=True)


def _run(monkeypatch, *, existing, overwrite, source=OTHER_SERVER, key="alice"):
    calls = SimpleNamespace(fetched=[], restored=[], imported=[])

    def fetch(src, key_, size, db, on_status=None):
        calls.fetched.append(key_)
        return f"/tmp/user-alice-20261119000000.tar.gz", True

    def restore(path, db, operator_is_admin=False, refuse_existing_user=False):
        calls.restored.append((path, refuse_existing_user))
        return {"username": "alice", "message": "Restored alice"}

    def foreign(path, kind=restore_sources.KIND_DA):
        calls.imported.append(kind)
        return {"username": "alice", "message": "Imported 1 domain(s): alice.test", "credentials": []}

    monkeypatch.setattr(restore_sources, "fetch", fetch)
    monkeypatch.setattr(maintenance.backup, "restore_user_backup", restore)
    monkeypatch.setattr(maintenance, "_restore_directadmin", foreign)
    monkeypatch.setattr(maintenance, "SessionLocal", lambda: _db(existing))
    monkeypatch.setattr(maintenance, "log_action", lambda *a, **k: None)
    kind = restore_sources.key_kind(source, key)
    job = maintenance._queue_backup_job(SimpleNamespace(id=7, role="admin"), "user_restore", "Restore queued",
                                        results=[{"name": key, "username": "alice", "kind": kind,
                                                  "status": "queued", "detail": ""}])
    maintenance._run_restore_job(job["job_id"], 7, source, [{"key": key, "size": 0, "username": "alice"}],
                                 True, overwrite)
    return calls, maintenance._public_backup_job(maintenance._get_backup_job(job["job_id"]), 7)


def test_an_account_already_here_is_refused_before_it_is_packed_there(monkeypatch):
    calls, job = _run(monkeypatch, existing="alice", overwrite=False)
    assert calls.fetched == [], "nothing is packed or downloaded on the other server"
    assert calls.restored == []
    assert job["results"][0]["status"] == "failed"
    assert "already on this server" in job["results"][0]["detail"]


def test_ticking_restore_over_restores_it(monkeypatch):
    calls, job = _run(monkeypatch, existing="alice", overwrite=True)
    assert calls.fetched == ["alice"]
    assert calls.restored == [("/tmp/user-alice-20261119000000.tar.gz", False)]
    assert job["results"][0]["status"] == "done"


def test_a_new_account_from_the_other_server_still_restores_and_stays_guarded(monkeypatch):
    calls, job = _run(monkeypatch, existing=None, overwrite=False)
    assert calls.restored == [("/tmp/user-alice-20261119000000.tar.gz", True)], \
        "the restore checks again: the archive could name a user other than the one listed"
    assert job["results"][0]["status"] == "done"


def test_this_servers_own_backup_still_restores_over_its_own_account(monkeypatch):
    # A local key names a file in the backup folder; none exists in this test.
    monkeypatch.setattr(restore_sources, "key_kind", lambda source, key: restore_sources.KIND_PANEL)
    calls, job = _run(monkeypatch, existing="alice", overwrite=False, source={"kind": "local"},
                      key="alice/user-alice-20261119000000.tar.gz")
    assert calls.restored and calls.restored[0][1] is False
    assert job["results"][0]["status"] == "done"


def test_a_directadmin_pull_keeps_overwriting_its_own_account(monkeypatch):
    source = {**OTHER_SERVER, "panel": "directadmin"}
    calls, job = _run(monkeypatch, existing="alice", overwrite=False, source=source)
    assert calls.imported == [restore_sources.KIND_DA]
    assert job["results"][0]["status"] == "done"


def test_the_page_marks_them_and_offers_to_restore_over_them():
    assert "t('Already here')" in APP
    assert "Restore over accounts already on this server ({names})" in APP
    assert "overwrite: crossNative && restoreOverwrite" in APP
    assert "Already on this server, so skipped: {names}." in APP
