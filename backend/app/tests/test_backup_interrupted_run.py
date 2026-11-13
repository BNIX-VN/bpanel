"""A Run now cut off by a panel restart does not leave its schedule
"running" for good (operator, 2026-11-13, .188: "Đang chạy mình update xong
giờ nó hết chạy rồi" - the update restarted the API half way through, and
Run now stayed greyed out)."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import BackupSchedule
from app.services import backup, backup_scheduler

MAIN = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_a_run_the_restart_cut_off_is_reported_and_the_rest_are_left_alone(db):
    db.add_all([
        BackupSchedule(id=1, all_users=True, user_ids="[]", last_status="running", last_message="Started by admin"),
        BackupSchedule(id=2, all_users=True, user_ids="[]", last_status="ok", last_message="ok 3 user(s)"),
    ])
    db.commit()

    assert backup_scheduler.release_interrupted_runs(db) == 1

    cut, fine = db.get(BackupSchedule, 1), db.get(BackupSchedule, 2)
    assert (cut.last_status, cut.last_message) == ("error", backup_scheduler.INTERRUPTED_MESSAGE)
    assert (fine.last_status, fine.last_message) == ("ok", "ok 3 user(s)")
    assert backup_scheduler.release_interrupted_runs(db) == 0


def test_the_api_releases_them_when_it_starts():
    assert "_release_interrupted_backup_runs()\n" in MAIN
    assert "backup_scheduler.sweep_after_restart()" in MAIN


# --- what a run cut off half way leaves on disk ------------------------------------------

def test_an_archive_gets_its_name_only_once_it_is_whole(tmp_path, monkeypatch):
    """.188 kept a cut-off user-toru-....tar.gz that Restore offered."""
    monkeypatch.setattr(backup.settings, "backup_root", str(tmp_path))
    monkeypatch.setattr(backup.settings, "command_dry_run", False)
    tmp_path = tmp_path / "users" / "toru"
    tmp_path.mkdir(parents=True)
    archive = tmp_path / "user-toru-20261113065348.tar.gz"
    with backup._written_whole(archive) as partial:
        assert partial.name == archive.name + ".part"
        partial.write_bytes(b"half")
        assert not archive.exists()
        # Being written, it is in no list of backups to restore.
        assert backup.list_user_backups("toru") == []
    assert archive.read_bytes() == b"half" and not partial.exists()
    assert backup.list_user_backups("toru") == [str(archive)]

    broken = tmp_path / "user-toru-20261113070000.tar.gz"
    with pytest.raises(RuntimeError):
        with backup._written_whole(broken) as partial:
            partial.write_bytes(b"half")
            raise RuntimeError("disk full")
    assert not broken.exists() and not partial.exists()


def test_the_restart_sweeps_unfinished_backups_and_keeps_finished_ones(tmp_path, monkeypatch):
    users = tmp_path / "users" / "toru"
    (users / "bpanel-user-backup-kbyui2lh").mkdir(parents=True)
    (users / "bpanel-user-backup-kbyui2lh" / "toru.erasvietnam.com.sql").write_text("dump")
    (users / "user-toru-20261113065348.tar.gz.part").write_bytes(b"half")
    (users / "user-toru-20261112170000.tar.gz").write_bytes(b"whole")
    site = tmp_path / "trezo.erasvietnam.com"
    site.mkdir()
    (site / "trezo.erasvietnam.com-20261113064730.tar.gz").write_bytes(b"whole")
    (site / "trezo.erasvietnam.com-20261113070000.tar.gz.part").write_bytes(b"half")

    monkeypatch.setattr(backup_scheduler, "_timer_run_going", lambda: True)
    monkeypatch.setattr(backup.settings, "backup_root", str(tmp_path))
    assert backup_scheduler.sweep_after_restart() == [], "the timer's runner may be writing one"

    monkeypatch.setattr(backup_scheduler, "_timer_run_going", lambda: False)
    removed = backup_scheduler.sweep_after_restart()
    assert sorted(Path(path).name for path in removed) == [
        "bpanel-user-backup-kbyui2lh", "trezo.erasvietnam.com-20261113070000.tar.gz.part",
        "user-toru-20261113065348.tar.gz.part"]
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == [
        "trezo.erasvietnam.com-20261113064730.tar.gz", "user-toru-20261112170000.tar.gz"]
