import json
import tarfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.core.secrets import decrypt, encrypt
from app.models.entities import BackupSchedule, DatabaseAccount, SftpBackupTarget, User, Website
from app.schemas.schemas import (
    BackupScheduleCreate,
    BackupScheduleOut,
    BackupCreate,
    CronCreate,
    CronDelete,
    PhpConfigUpdate,
    RestoreBackup,
    SftpBackupRun,
    SftpBackupTargetCreate,
    SftpBackupTargetOut,
    UserBackupCreate,
    UserRestoreBackup,
    WpAction,
)
from app.services import backup, cron, file_manager, php, site_users, storage_quota, wordpress
from app.services.audit import log_action

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class FileWrite(BaseModel):
    website_id: int
    path: str
    content: str


class FileMkdir(BaseModel):
    website_id: int
    path: str = "public"
    name: str


class FileRename(BaseModel):
    website_id: int
    path: str
    new_name: str


class FileBulkDelete(BaseModel):
    website_id: int
    paths: list[str]


class FileArchive(BaseModel):
    website_id: int
    base_path: str = "public"
    paths: list[str]
    output_name: str = ""
    format: str = "zip"


class FileExtract(BaseModel):
    website_id: int
    archive_path: str
    destination_path: str = ""


def get_owned_website(db: Session, current_user: User, website_id: int) -> Website:
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    return website


def get_backup_user(db: Session, current_user: User, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    return user


def upload_archive_to_target(db: Session, target_id: int, archive: str) -> tuple[str, str]:
    target = db.query(SftpBackupTarget).filter(SftpBackupTarget.id == target_id).first()
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="SFTP target not found")
    try:
        result = backup.upload_to_sftp(
            archive,
            host=target.host,
            port=target.port,
            username=target.username,
            password=decrypt(target.password) if target.password else None,
            private_key=decrypt(target.private_key) if target.private_key else None,
            remote_path=target.remote_path,
            expected_host_key_type=target.host_key_type,
            expected_host_key_fingerprint=target.host_key_fingerprint,
        )
    except backup.SftpHostKeyMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not target.host_key_fingerprint and result.get("host_key_fingerprint"):
        target.host_key_type = result["host_key_type"]
        target.host_key_fingerprint = result["host_key_fingerprint"]
        db.commit()
    return target.name, result["remote_file"]


def _save_user_restore_upload(file: UploadFile) -> dict:
    target = ""
    try:
        target = backup.save_uploaded_user_backup(file.filename or "user-backup.tar.gz", file.file)
        manifest = backup.read_backup_manifest(target)
        if manifest.get("kind") != "bpanel_user":
            raise ValueError("This is not a full user backup")
    except (ValueError, FileNotFoundError) as exc:
        if target:
            try:
                backup.delete_user_backup(target)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = backup.user_backup_path(target)
    return {
        "backup_file": target,
        "filename": path.name,
        "username": (manifest.get("user") or {}).get("username"),
        "generated_at": manifest.get("generated_at"),
        "websites": len(manifest.get("websites") or []),
        "size": path.stat().st_size,
        "valid": True,
        "error": "",
    }


def _quota_check_for_website(db: Session, website: Website):
    owner = website.owner

    def check(incoming_bytes: int, replaced_bytes: int = 0) -> None:
        storage_quota.enforce_user_storage_quota(
            db,
            owner,
            incoming_bytes=incoming_bytes,
            replaced_bytes=replaced_bytes,
        )

    return check


@router.post("/backup")
def create_backup(payload: BackupCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, payload.website_id)
    db_item = db.query(DatabaseAccount).filter(DatabaseAccount.website_id == website.id).first()
    archive = backup.create_backup(website, db_item.db_name if db_item else None)
    log_action(db, current_user.id, "backup", website.domain, archive)
    return {"backup_file": archive}


@router.post("/restore")
def restore_backup(payload: RestoreBackup, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        path = backup.restore_backup(website, payload.backup_file)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if website.linux_user:
        runtime_php_version = website.php_version if (website.app_type or "wordpress") in {"wordpress", "php"} else None
        site_users.ensure_site_runtime(website.domain, website.root_path, runtime_php_version, website.linux_user)
    wordpress.fix_permissions(website.root_path, website.linux_user)
    log_action(db, current_user.id, "restore", website.domain, payload.backup_file)
    return {"restored_to": path}


@router.get("/backups/{website_id}")
def list_backups(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    return {"items": backup.list_backups(website.domain)}


@router.get("/backups/{website_id}/download")
def download_backup(website_id: int, backup_file: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    try:
        path = backup.backup_path(website.domain, backup_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Backup not found") from exc
    return FileResponse(str(path), filename=path.name, media_type="application/gzip")


@router.delete("/backups/{website_id}")
def delete_backup(website_id: int, backup_file: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    try:
        deleted = backup.delete_backup(website.domain, backup_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Backup not found")
    log_action(db, current_user.id, "delete_backup", website.domain, deleted)
    return {"deleted": deleted}


@router.post("/backups/{website_id}/upload")
def upload_backup(website_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    try:
        target = backup.save_uploaded_backup(website.domain, file.filename or "backup.tar.gz", file.file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "upload_backup", website.domain, target)
    return {"backup_file": target}


@router.get("/user-restore-backups")
def list_user_restore_backups(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return {"directory": backup.user_restore_dir(), "items": backup.list_user_restore_backups()}


@router.post("/user-restore-backups/upload")
def upload_user_restore_backups(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    if not files:
        raise HTTPException(status_code=400, detail="No backup files uploaded")
    items = [_save_user_restore_upload(file) for file in files]
    users = ", ".join(item.get("username") or item.get("filename") or "user" for item in items)
    log_action(db, current_user.id, "upload_user_restore_backups", "restore_folder", users)
    return {"directory": backup.user_restore_dir(), "items": items}


@router.delete("/user-restore-backups")
def delete_user_restore_backup(backup_file: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        deleted = backup.delete_user_restore_backup(backup_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Backup not found") from exc
    log_action(db, current_user.id, "delete_user_restore_backup", "restore_folder", deleted, request=request)
    return {"deleted": deleted}


@router.get("/user-backups/{user_id}")
def list_user_backups(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = get_backup_user(db, current_user, user_id)
    items = backup.list_user_backups(user.username)
    if is_admin_role(current_user.role):
        items.extend(item for item in backup.list_uploaded_user_backups(user.username) if item not in items)
    return {"items": items}


@router.post("/user-backup")
def create_user_backup(payload: UserBackupCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = get_backup_user(db, current_user, payload.user_id)
    archive = backup.create_user_backup(user, db)
    remote_file = None
    target_name = None
    if payload.target_id:
        ensure_role(current_user.role, Role.admin)
        target_name, remote_file = upload_archive_to_target(db, payload.target_id, archive)
    detail = f"{archive}" + (f" -> {target_name}:{remote_file}" if remote_file else "")
    log_action(db, current_user.id, "backup_user", user.username, detail, request=request)
    return {"backup_file": archive, "remote_file": remote_file, "target": target_name}


@router.get("/user-backups-download")
def download_user_backup(backup_file: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        path = backup.user_backup_path(backup_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Backup not found") from exc
    return FileResponse(str(path), filename=path.name, media_type="application/gzip")


@router.post("/user-backups/upload")
def upload_user_backup(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    item = _save_user_restore_upload(file)
    log_action(db, current_user.id, "upload_user_backup", item.get("username") or "user", item["backup_file"])
    return {"backup_file": item["backup_file"], "username": item.get("username")}


@router.post("/user-restore")
def restore_user_backup(payload: UserRestoreBackup, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        result = backup.restore_user_backup(payload.backup_file, db)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "restore_user", result.get("username", "user"), payload.backup_file, request=request)
    return result


@router.delete("/user-backups")
def delete_user_backup(backup_file: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        deleted = backup.delete_user_backup(backup_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Backup not found") from exc
    log_action(db, current_user.id, "delete_user_backup", "user", deleted, request=request)
    return {"deleted": deleted}


@router.get("/backup-schedules", response_model=list[BackupScheduleOut])
def list_backup_schedules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return db.query(BackupSchedule).order_by(BackupSchedule.id.desc()).all()


@router.post("/backup-schedules", response_model=BackupScheduleOut)
def create_backup_schedule(payload: BackupScheduleCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    user_ids = [] if payload.all_users else (payload.user_ids or ([payload.user_id] if payload.user_id else []))
    user_ids = sorted({int(user_id) for user_id in user_ids if int(user_id) > 0})
    users = []
    if not payload.all_users:
        if not user_ids:
            raise HTTPException(status_code=400, detail="Select at least one user")
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        found_ids = {user.id for user in users}
        missing_ids = [str(user_id) for user_id in user_ids if user_id not in found_ids]
        if missing_ids:
            raise HTTPException(status_code=404, detail=f"User not found: {', '.join(missing_ids)}")
    if payload.target_id and not db.query(SftpBackupTarget).filter(SftpBackupTarget.id == payload.target_id, SftpBackupTarget.is_active == True).first():  # noqa: E712
        raise HTTPException(status_code=404, detail="SFTP target not found")
    item = BackupSchedule(
        user_id=user_ids[0] if user_ids else None,
        user_ids=json.dumps(user_ids),
        all_users=payload.all_users,
        target_id=payload.target_id,
        schedule=payload.schedule,
        retention=payload.retention,
        is_active=payload.is_active,
        last_status="pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    target = "all_users" if payload.all_users else ",".join(user.username for user in users)
    log_action(db, current_user.id, "create_backup_schedule", target, payload.schedule, request=request)
    return item


@router.delete("/backup-schedules/{schedule_id}")
def delete_backup_schedule(schedule_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    item = db.query(BackupSchedule).filter(BackupSchedule.id == schedule_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backup schedule not found")
    db.delete(item)
    db.commit()
    log_action(db, current_user.id, "delete_backup_schedule", str(schedule_id), request=request)
    return {"ok": True}


@router.get("/sftp-targets", response_model=list[SftpBackupTargetOut])
def list_sftp_targets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return db.query(SftpBackupTarget).order_by(SftpBackupTarget.id.desc()).all()


@router.post("/sftp-targets", response_model=SftpBackupTargetOut)
def create_sftp_target(
    payload: SftpBackupTargetCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    if db.query(SftpBackupTarget).filter(SftpBackupTarget.name == payload.name).first():
        raise HTTPException(status_code=409, detail="SFTP target name already exists")
    if not payload.password and not payload.private_key:
        raise HTTPException(status_code=400, detail="SFTP password or private key is required")
    target = SftpBackupTarget(
        name=payload.name,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=encrypt(payload.password) if payload.password else None,
        private_key=encrypt(payload.private_key) if payload.private_key else None,
        remote_path=payload.remote_path,
        is_active=True,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    log_action(db, current_user.id, "create_sftp_target", target.name, request=request)
    return target


@router.delete("/sftp-targets/{target_id}")
def delete_sftp_target(
    target_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    target = db.query(SftpBackupTarget).filter(SftpBackupTarget.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="SFTP target not found")
    name = target.name
    db.delete(target)
    db.commit()
    log_action(db, current_user.id, "delete_sftp_target", name, request=request)
    return {"ok": True}


@router.post("/backup-sftp")
def create_sftp_backup(
    payload: SftpBackupRun,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    website = get_owned_website(db, current_user, payload.website_id)
    target = db.query(SftpBackupTarget).filter(SftpBackupTarget.id == payload.target_id).first()
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="SFTP target not found")
    db_item = db.query(DatabaseAccount).filter(DatabaseAccount.website_id == website.id).first()
    archive = backup.create_backup(website, db_item.db_name if db_item else None)
    try:
        result = backup.upload_to_sftp(
            archive,
            host=target.host,
            port=target.port,
            username=target.username,
            password=decrypt(target.password) if target.password else None,
            private_key=decrypt(target.private_key) if target.private_key else None,
            remote_path=target.remote_path,
            expected_host_key_type=target.host_key_type,
            expected_host_key_fingerprint=target.host_key_fingerprint,
        )
    except backup.SftpHostKeyMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not target.host_key_fingerprint and result.get("host_key_fingerprint"):
        target.host_key_type = result["host_key_type"]
        target.host_key_fingerprint = result["host_key_fingerprint"]
        db.commit()
    remote_file = result["remote_file"]
    log_action(db, current_user.id, "backup_sftp", website.domain, f"{target.name}:{remote_file}", request=request)
    return {"backup_file": archive, "remote_file": remote_file, "target": target.name}


@router.get("/php-config")
def get_php_config(php_version: str = Query(default="8.3"), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        return php.read_php_ini(php_version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/php-config")
def update_php_config(payload: PhpConfigUpdate, current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        target = php.update_php_ini(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"target": target}


@router.post("/cron")
def add_cron(payload: CronCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        line = cron.add_cron(website, payload.schedule, payload.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"line": line}


@router.get("/cron/{website_id}")
def list_cron(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    return {"items": cron.list_cron(website.domain, website.linux_user or "www-data")}


@router.delete("/cron")
def delete_cron(payload: CronDelete, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, payload.website_id)
    line = cron.delete_cron(website.domain, payload.index, website.linux_user or "www-data")
    log_action(db, current_user.id, "delete_cron", website.domain, line)
    return {"deleted": line}


@router.post("/wordpress")
def wordpress_action(payload: WpAction, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, payload.website_id)
    result = wordpress.wp_update(f"{website.root_path}/public", payload.action, website.linux_user)
    return result.__dict__


@router.post("/wordpress/{website_id}/fix-permissions")
def fix_wordpress_permissions(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    if website.linux_user:
        runtime_php_version = website.php_version if (website.app_type or "wordpress") in {"wordpress", "php"} else None
        site_users.ensure_site_runtime(website.domain, website.root_path, runtime_php_version, website.linux_user)
    wordpress.fix_permissions(website.root_path, website.linux_user)
    log_action(db, current_user.id, "fix_permissions", website.domain, website.root_path)
    return {"message": f"Fixed permissions for {website.domain}", "root_path": website.root_path}


@router.get("/files/{website_id}")
def list_files(website_id: int, path: str = Query(default=""), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    return {"items": file_manager.list_files(website, path)}


@router.get("/files/{website_id}/read")
def read_file(website_id: int, path: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    try:
        content = file_manager.read_text_file(
            website,
            path,
            allow_sensitive=is_admin_role(current_user.role),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"content": content}


@router.get("/files/{website_id}/download")
def download_file(website_id: int, path: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = get_owned_website(db, current_user, website_id)
    try:
        target = file_manager.download_file_path(website, path, allow_sensitive=is_admin_role(current_user.role))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(str(target), filename=target.name)


@router.post("/files/mkdir")
def make_directory(payload: FileMkdir, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        target = file_manager.make_directory(website, payload.path, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "mkdir", website.domain, target)
    return {"target": target}


@router.post("/files/rename")
def rename_entry(payload: FileRename, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        target = file_manager.rename_entry(website, payload.path, payload.new_name, is_admin_role(current_user.role))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "rename_file", website.domain, target)
    return {"target": target}


@router.post("/files/delete")
def delete_entries(payload: FileBulkDelete, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        deleted = file_manager.delete_entries(website, payload.paths, is_admin_role(current_user.role))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "delete_files", website.domain, ",".join(payload.paths[:20]))
    return {"deleted": deleted}


@router.post("/files/archive")
def archive_entries(payload: FileArchive, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        target = file_manager.archive_entries(
            website,
            payload.base_path,
            payload.paths,
            payload.output_name,
            payload.format,
            allow_sensitive=is_admin_role(current_user.role),
            quota_check=_quota_check_for_website(db, website),
        )
    except storage_quota.StorageQuotaExceeded as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "archive_files", website.domain, target)
    return {"target": target}


@router.post("/files/extract")
def extract_archive(payload: FileExtract, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        target = file_manager.extract_archive(
            website,
            payload.archive_path,
            payload.destination_path,
            True,
            quota_check=_quota_check_for_website(db, website),
        )
    except storage_quota.StorageQuotaExceeded as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except (ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "extract_archive", website.domain, payload.archive_path)
    return {"target": target}


@router.post("/files/write")
def write_file(payload: FileWrite, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        target = file_manager.write_text_file(
            website,
            payload.path,
            payload.content,
            is_admin_role(current_user.role),
            quota_check=_quota_check_for_website(db, website),
        )
    except storage_quota.StorageQuotaExceeded as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"target": target}


@router.post("/files/{website_id}/upload")
def upload_file(
    website_id: int,
    path: str = Query(default="public"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, website_id)
    try:
        target = file_manager.upload_file(
            website,
            path,
            file.filename or "upload.bin",
            file.file,
            is_admin_role(current_user.role),
            quota_check=_quota_check_for_website(db, website),
        )
    except storage_quota.StorageQuotaExceeded as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "upload_file", website.domain, target)
    return {"target": target}


@router.delete("/files/{website_id}")
def delete_file(website_id: int, path: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = get_owned_website(db, current_user, website_id)
    try:
        target = file_manager.delete_file(website, path, is_admin_role(current_user.role))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": target}
