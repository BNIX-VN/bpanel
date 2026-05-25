from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.config import settings
from app.core.security import ALGORITHM
from app.core.permissions import Role, ensure_role
from app.core.secrets import decrypt, encrypt
from app.models.entities import DatabaseAccount, SftpBackupTarget, User, Website
from app.schemas.schemas import (
    BackupCreate,
    CronCreate,
    CronDelete,
    PhpConfigUpdate,
    RestoreBackup,
    SftpBackupRun,
    SftpBackupTargetCreate,
    SftpBackupTargetOut,
    WpAction,
)
from app.services import backup, cron, file_manager, panel_urls, php, site_users, wordpress
from app.services.audit import log_action

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class FileWrite(BaseModel):
    website_id: int
    path: str
    content: str


class FileBrowserOpen(BaseModel):
    website_id: Optional[int] = None


FILEBROWSER_COOKIE = "BPanelFileBrowser"
FILEBROWSER_LOGIN_TTL_SECONDS = 60
FILEBROWSER_SESSION_TTL_SECONDS = 8 * 60 * 60


def get_owned_website(db: Session, current_user: User, website_id: int) -> Website:
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    return website


def _make_filebrowser_token(username: str, kind: str, ttl_seconds: int, redirect: str = "/filebrowser/", base_url: str = "") -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return jwt.encode(
        {"sub": username, "kind": kind, "redirect": redirect, "base_url": base_url, "exp": expire},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def _decode_filebrowser_token(token: str, expected_kind: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid File Browser session") from exc
    if payload.get("kind") != expected_kind or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid File Browser session")
    return payload


def _filebrowser_redirect_for(website: Optional[Website]) -> str:
    if not website:
        return "/filebrowser/files/"
    root_path = Path(website.root_path).resolve()
    try:
        relative_path = root_path.relative_to(Path("/home")).as_posix()
    except ValueError:
        try:
            relative_path = root_path.relative_to(Path(settings.sites_root).resolve()).as_posix()
        except ValueError:
            relative_path = website.domain
    return f"/filebrowser/files/{quote(f'{relative_path}/public', safe='/._-')}"


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
        runtime_php_version = website.php_version if (website.app_type or "wordpress") == "wordpress" else None
        site_users.ensure_site_runtime(website.domain, website.root_path, runtime_php_version)
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
        remote_file = backup.upload_to_sftp(
            archive,
            host=target.host,
            port=target.port,
            username=target.username,
            password=decrypt(target.password) if target.password else None,
            private_key=decrypt(target.private_key) if target.private_key else None,
            remote_path=target.remote_path,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
        runtime_php_version = website.php_version if (website.app_type or "wordpress") == "wordpress" else None
        site_users.ensure_site_runtime(website.domain, website.root_path, runtime_php_version)
    wordpress.fix_permissions(website.root_path, website.linux_user)
    log_action(db, current_user.id, "fix_permissions", website.domain, website.root_path)
    return {"message": f"Fixed permissions for {website.domain}", "root_path": website.root_path}


@router.post("/filebrowser")
def open_filebrowser(payload: FileBrowserOpen, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    website = get_owned_website(db, current_user, payload.website_id) if payload.website_id else None
    redirect = _filebrowser_redirect_for(website)
    token = _make_filebrowser_token(
        current_user.username,
        "filebrowser-login",
        FILEBROWSER_LOGIN_TTL_SECONDS,
        redirect,
        panel_urls.tools_base_url(request),
    )
    return {"url": f"/api/maintenance/filebrowser-sso/{token}"}


@router.get("/filebrowser-sso/{token}")
def filebrowser_sso(token: str, request: Request, db: Session = Depends(get_db)):
    payload = _decode_filebrowser_token(token, "filebrowser-login")
    user = db.query(User).filter(User.username == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid File Browser session")
    ensure_role(user.role, Role.admin)
    redirect = payload.get("redirect") or "/filebrowser/"
    if not isinstance(redirect, str) or not redirect.startswith("/filebrowser/"):
        redirect = "/filebrowser/"
    base_url = payload.get("base_url") or panel_urls.tools_base_url(request)
    if not isinstance(base_url, str) or not (base_url.startswith("http://") or base_url.startswith("https://")):
        base_url = panel_urls.tools_base_url(request)
    session_token = _make_filebrowser_token(user.username, "filebrowser-session", FILEBROWSER_SESSION_TTL_SECONDS, redirect, base_url)
    response = RedirectResponse(f"{base_url}{redirect}", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        FILEBROWSER_COOKIE,
        session_token,
        max_age=FILEBROWSER_SESSION_TTL_SECONDS,
        path="/filebrowser/",
        secure=base_url.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/filebrowser-auth")
def filebrowser_auth(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(FILEBROWSER_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing File Browser session")
    payload = _decode_filebrowser_token(token, "filebrowser-session")
    user = db.query(User).filter(User.username == payload["sub"]).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid File Browser session")
    ensure_role(user.role, Role.admin)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "no-store", "X-Bpanel-User": "admin"},
    )


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
            allow_sensitive=current_user.role in {"super_admin", "admin"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"content": content}


@router.post("/files/write")
def write_file(payload: FileWrite, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Readonly users must not write.
    ensure_role(current_user.role, Role.user)
    website = get_owned_website(db, current_user, payload.website_id)
    try:
        target = file_manager.write_text_file(website, payload.path, payload.content, current_user.role in {"super_admin", "admin"})
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
    ensure_role(current_user.role, Role.user)
    website = get_owned_website(db, current_user, website_id)
    try:
        target = file_manager.upload_file(
            website,
            path,
            file.filename or "upload.bin",
            file.file,
            current_user.role in {"super_admin", "admin"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "upload_file", website.domain, target)
    return {"target": target}


@router.delete("/files/{website_id}")
def delete_file(website_id: int, path: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.user)
    website = get_owned_website(db, current_user, website_id)
    try:
        target = file_manager.delete_file(website, path, current_user.role in {"super_admin", "admin"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": target}
