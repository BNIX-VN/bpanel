"""A backup destination and a backup schedule can be edited (operator,
2026-11-13: "cái nơi lưu nên cho edit, lịch cũng cho edit"), as on OPanel.

Before, the only way to change either was to delete it and add it again,
which also threw away a destination's pinned host key and every schedule
pointing at it.
"""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import maintenance
from app.core.database import Base
from app.core.secrets import decrypt, encrypt
from app.models.entities import BackupSchedule, SftpBackupTarget, User
from app.schemas.schemas import BackupScheduleCreate, SftpBackupTargetUpdate
from app.services import backup_s3

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
    session.commit()
    yield session
    session.close()


@pytest.fixture
def admin(db):
    return db.get(User, 1)


def _sftp(db, **changes):
    target = SftpBackupTarget(name="nas", kind="sftp", host="nas.example.test", port=9923, username="backup",
                              password=encrypt("first-pass"), remote_path="/backups",
                              host_key_type="ssh-ed25519", host_key_fingerprint="SHA256:pinned", is_active=True)
    for key, value in changes.items():
        setattr(target, key, value)
    db.add(target)
    db.commit()
    return target


def _edit(target, **changes):
    fields = {"name": target.name, "kind": target.kind, "host": target.host, "port": target.port,
              "username": target.username, "remote_path": target.remote_path,
              "endpoint": target.endpoint, "region": target.region, "bucket": target.bucket,
              "access_key": target.access_key, "prefix": target.prefix, "secure": target.secure}
    fields.update(changes)
    return SftpBackupTargetUpdate(**fields)


# --- schedules -------------------------------------------------------------------------------

def test_every_setting_of_a_schedule_can_be_changed(db, admin):
    _sftp(db)
    item = BackupSchedule(user_ids=json.dumps([2]), user_id=2, all_users=False, schedule="0 0 * * *",
                          name_suffix="week_of_month", retention=7, is_active=True, last_status="ok")
    db.add(item)
    db.commit()

    maintenance.update_backup_schedule(item.id, BackupScheduleCreate(
        user_ids=[2, 3], schedule="30 3 * * 1", target_id=1, name_suffix="day_of_week", retention=14, is_active=False,
    ), request=None, db=db, current_user=admin)

    db.refresh(item)
    assert json.loads(item.user_ids) == [2, 3] and item.user_id == 2 and not item.all_users
    assert (item.schedule, item.target_id, item.name_suffix, item.retention, item.is_active) == \
        ("30 3 * * 1", 1, "day_of_week", 14, False)
    # What the last run said is the last run's, not the edit's.
    assert item.last_status == "ok"


def test_editing_a_schedule_that_is_gone_says_so(db, admin):
    with pytest.raises(HTTPException) as exc:
        maintenance.update_backup_schedule(99, BackupScheduleCreate(all_users=True), request=None, db=db, current_user=admin)
    assert exc.value.status_code == 404


def test_an_edited_schedule_is_checked_like_a_new_one(db, admin):
    item = BackupSchedule(all_users=True, user_ids="[]", schedule="0 0 * * *", last_status="pending")
    db.add(item)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        maintenance.update_backup_schedule(item.id, BackupScheduleCreate(user_ids=[42]), request=None, db=db, current_user=admin)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        maintenance.update_backup_schedule(item.id, BackupScheduleCreate(all_users=True, target_id=7),
                                           request=None, db=db, current_user=admin)
    assert exc.value.status_code == 404


# --- SFTP destinations -----------------------------------------------------------------------

def test_a_password_left_empty_keeps_the_saved_one(db, admin):
    target = _sftp(db)
    maintenance.update_sftp_target(target.id, _edit(target, name="nas-2", remote_path="/srv/bk"),
                                   request=None, db=db, current_user=admin)
    db.refresh(target)
    assert (target.name, target.remote_path) == ("nas-2", "/srv/bk")
    assert decrypt(target.password) == "first-pass"
    # Same server: its pinned key stays.
    assert target.host_key_fingerprint == "SHA256:pinned"

    maintenance.update_sftp_target(target.id, _edit(target, password="second-pass"), request=None, db=db, current_user=admin)
    db.refresh(target)
    assert decrypt(target.password) == "second-pass"


@pytest.mark.parametrize("change", [{"host": "other.example.test"}, {"port": 22}, {"reset_host_key": True}])
def test_another_server_or_a_rebuilt_one_forgets_the_pinned_key(db, admin, change):
    target = _sftp(db)
    maintenance.update_sftp_target(target.id, _edit(target, **change), request=None, db=db, current_user=admin)
    db.refresh(target)
    assert target.host_key_type is None and target.host_key_fingerprint is None


def test_a_destination_keeps_its_kind_and_a_unique_name(db, admin):
    target = _sftp(db)
    _sftp(db, name="other")
    with pytest.raises(HTTPException) as exc:
        maintenance.update_sftp_target(target.id, _edit(target, kind="s3", endpoint="s3.example.test", bucket="backups",
                                                        access_key="ak"), request=None, db=db, current_user=admin)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        maintenance.update_sftp_target(target.id, _edit(target, name="other"), request=None, db=db, current_user=admin)
    assert exc.value.status_code == 409


# --- S3 destinations -------------------------------------------------------------------------

def _s3(db):
    target = SftpBackupTarget(name="wasabi", kind="s3", host="", port=22, username="", remote_path="/",
                              endpoint="s3.wasabisys.com", bucket="old-bucket", access_key="AK",
                              secret_key=encrypt("old-secret"), secure=True, is_active=True)
    db.add(target)
    db.commit()
    return target


def test_an_edited_bucket_is_checked_before_it_is_kept(db, admin, monkeypatch):
    target = _s3(db)
    seen = []

    def check(row):
        seen.append((row.bucket, decrypt(row.secret_key)))
        if row.bucket == "missing-bucket":
            raise backup_s3.S3Error("NoSuchBucket")
        return {}

    monkeypatch.setattr(backup_s3, "check", check)
    maintenance.update_sftp_target(target.id, _edit(target, bucket="new-bucket"), request=None, db=db, current_user=admin)
    db.refresh(target)
    # The secret left empty is the saved one, and the check used it.
    assert seen == [("new-bucket", "old-secret")] and target.bucket == "new-bucket"

    with pytest.raises(HTTPException) as exc:
        maintenance.update_sftp_target(target.id, _edit(target, bucket="missing-bucket", secret_key="new-secret"),
                                       request=None, db=db, current_user=admin)
    assert exc.value.status_code == 400
    db.refresh(target)
    assert target.bucket == "new-bucket" and decrypt(target.secret_key) == "old-secret"


# --- the page --------------------------------------------------------------------------------

def test_the_page_offers_edit_and_saves_with_put():
    assert "label: t('Edit schedule')" in APP and "label: t('Edit destination')" in APP
    assert "`/maintenance/backup-schedules/${editing}`" in APP
    assert "`/maintenance/sftp-targets/${editing}`" in APP
    assert "method: editing ? 'PUT' : 'POST'" in APP
