"""Run now says where it is (operator, 2026-11-13, .188: "không hiện tiến
độ backup" - the row showed a bar with nothing in it until all 15 accounts
were through, and the page stopped looking after five minutes)."""
import io
import tarfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import maintenance
from app.core.database import Base
from app.models.entities import BackupSchedule, User
from app.services import backup, backup_scheduler

APP = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(maintenance, "log_action", lambda *a, **k: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, username="admin", email="a@example.test", role="admin", hashed_password="x", is_active=True),
        User(id=2, username="alice", email="b@example.test", role="end_user", hashed_password="x", is_active=True),
        User(id=3, username="bob", email="c@example.test", role="end_user", hashed_password="x", is_active=True),
    ])
    session.add(BackupSchedule(id=1, all_users=True, user_ids="[]", target_id=7, schedule="0 2 * * *",
                               last_status="pending"))
    session.commit()
    yield session
    session.close()


def test_a_run_reports_each_account_its_step_and_who_is_through(db, monkeypatch):
    def pack(user, _db, skipped=None, on_progress=None):
        on_progress(0.0, "databases")
        on_progress(0.5, f"{user.username}.example")
        if user.username == "bob":
            raise RuntimeError("disk full")
        return f"/tmp/user-{user.username}.tar.gz"

    def send(_db, _schedule, archive, on_progress=None):
        on_progress(50, 100)
        on_progress(100, 100)
        return f"nas:{archive}"

    monkeypatch.setattr(backup, "create_user_backup", pack)
    monkeypatch.setattr(backup_scheduler, "_upload_if_configured", send)
    monkeypatch.setattr(backup, "discard_local_copy", lambda archive: None)
    monkeypatch.setattr(backup, "prune_user_backups", lambda *a: None)
    monkeypatch.setattr(backup_scheduler, "_notify_failure", lambda *a: None)
    heard = []

    backup_scheduler.run_one(db, db.get(BackupSchedule, 1), on_progress=heard.append)

    percents = [state["percent"] for state in heard]
    assert percents == sorted(percents) and percents[-1] == 100.0
    assert {(state["on"], state["index"], state["total"]) for state in heard} == {
        ("admin", 1, 3), ("alice", 2, 3), ("bob", 3, 3)}
    assert {state["step"] for state in heard} >= {"databases", "admin.example", "uploading"}
    assert heard[-1]["done"] == ["admin", "alice"] and heard[-1]["failed"] == ["bob"]
    # Packing is most of an account's share, sending the rest.
    assert next(s for s in heard if s["on"] == "admin" and s["step"] == "uploading")["percent"] == pytest.approx(28.3, abs=0.1)


def test_the_bytes_of_a_website_are_counted_as_they_are_packed(tmp_path):
    site = tmp_path / "site"
    (site / "wp-content").mkdir(parents=True)
    (site / "index.php").write_bytes(b"x" * 300)
    (site / "wp-content" / "big.jpg").write_bytes(b"y" * 700)
    heard = []
    with tarfile.open(fileobj=io.BytesIO(), mode="w:gz") as tar:
        backup._add_tree(tar, site, "site", [], on_bytes=heard.append)
    assert sorted(heard) == [300, 700]
    assert backup._tree_size(site) == 1000


def test_the_list_carries_the_progress_of_a_run_and_only_while_it_runs(db, monkeypatch):
    admin = db.get(User, 1)
    db.get(BackupSchedule, 1).last_status = "running"
    db.commit()
    state = {"percent": 41.5, "on": "alice", "index": 2, "total": 3, "step": "uploading", "done": ["admin"], "failed": []}
    monkeypatch.setitem(maintenance._schedule_progress, 1, state)
    [row] = maintenance.list_backup_schedules(db=db, current_user=admin)
    assert row.progress == state

    db.get(BackupSchedule, 1).last_status = "ok"
    db.commit()
    [row] = maintenance.list_backup_schedules(db=db, current_user=admin)
    assert row.progress is None


def test_a_schedule_already_running_is_not_started_twice(db, monkeypatch):
    admin = db.get(User, 1)
    db.get(BackupSchedule, 1).last_status = "running"
    db.commit()
    submitted = []
    monkeypatch.setattr(maintenance._backup_job_executor, "submit", lambda *a: submitted.append(a))
    with pytest.raises(HTTPException) as exc:
        maintenance.run_backup_schedule_now(1, request=None, db=db, current_user=admin)
    assert exc.value.status_code == 409 and submitted == []


def test_the_page_shows_it_and_follows_the_run_to_its_end():
    assert "item.progress?.total" in APP and "style={{ width: `${pct}%` }}" in APP
    assert "t('Done ({n}): {names}'" in APP
    poll = APP.split("function pollBackupSchedule(")[1].split("\n  }\n")[0]
    assert "attempts" not in poll, "it stopped looking after five minutes"
    assert "data.filter(row => row.last_status === 'running').forEach(row => pollBackupSchedule(row.id))" in APP
