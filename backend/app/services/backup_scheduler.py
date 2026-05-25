from datetime import datetime

from app.core.database import SessionLocal
from app.core.secrets import decrypt
from app.models.entities import BackupSchedule, SftpBackupTarget, User
from app.services import backup


def _field_matches(field: str, value: int) -> bool:
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = max(int(step_text or "1"), 1)
        if part == "*":
            start, end = 0, 59
        elif "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(part)
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def _cron_due(schedule: str, now: datetime) -> bool:
    minute, hour, day, month, weekday = schedule.split()
    cron_weekday = (now.weekday() + 1) % 7
    return (
        _field_matches(minute, now.minute)
        and _field_matches(hour, now.hour)
        and _field_matches(day, now.day)
        and _field_matches(month, now.month)
        and (_field_matches(weekday, cron_weekday) or (cron_weekday == 0 and _field_matches(weekday, 7)))
    )


def _upload_if_configured(db, schedule: BackupSchedule, archive: str) -> str:
    if not schedule.target_id:
        return archive
    target = db.query(SftpBackupTarget).filter(SftpBackupTarget.id == schedule.target_id, SftpBackupTarget.is_active == True).first()  # noqa: E712
    if not target:
        raise ValueError("SFTP target not found")
    remote_file = backup.upload_to_sftp(
        archive,
        host=target.host,
        port=target.port,
        username=target.username,
        password=decrypt(target.password) if target.password else None,
        private_key=decrypt(target.private_key) if target.private_key else None,
        remote_path=target.remote_path,
    )
    return f"{target.name}:{remote_file}"


def run_due_schedules(now: datetime | None = None) -> int:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    db = SessionLocal()
    ran = 0
    try:
        schedules = db.query(BackupSchedule).filter(BackupSchedule.is_active == True).all()  # noqa: E712
        for schedule in schedules:
            if not _cron_due(schedule.schedule, now):
                continue
            if schedule.last_run_at and schedule.last_run_at.replace(second=0, microsecond=0) == now:
                continue
            user = db.query(User).filter(User.id == schedule.user_id).first()
            if not user:
                schedule.last_run_at = now
                schedule.last_status = "error"
                schedule.last_message = "User not found"
                db.commit()
                continue
            try:
                archive = backup.create_user_backup(user, db)
                message = _upload_if_configured(db, schedule, archive)
                backup.prune_user_backups(user.username, schedule.retention)
                schedule.last_status = "ok"
                schedule.last_message = message
                ran += 1
            except Exception as exc:  # pragma: no cover - operational path
                schedule.last_status = "error"
                schedule.last_message = str(exc)[:1000]
            finally:
                schedule.last_run_at = now
                db.commit()
    finally:
        db.close()
    return ran


if __name__ == "__main__":
    count = run_due_schedules()
    print(f"BPanel backup scheduler ran {count} job(s).")
