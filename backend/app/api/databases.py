from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import List
import ipaddress
import logging

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.access import ensure_owner_access, scope_owner
from app.core.permissions import Role, ensure_role, is_admin_role
from app.core.secrets import decrypt, encrypt
from app.models.entities import DatabaseAccount, User, Website
from app.schemas.schemas import (
    DatabaseCreate, DatabaseCreatedOut, DatabaseOut, DatabaseOwnerUpdate, DatabasePasswordUpdate,
)
from app.services import mariadb, panel_urls, reseller as reseller_pool
from app.services.audit import log_action
from app.services.sso_tokens import consume_phpmyadmin_token, create_phpmyadmin_token

router = APIRouter(prefix="/databases", tags=["databases"])

logger = logging.getLogger("bpanel.databases")


def _is_loopback_peer(request: Request) -> bool:
    """Return True if the immediate TCP peer is loopback.

    With ``--forwarded-allow-ips 127.0.0.1`` (see installer/install.sh) any
    X-Forwarded-For from a non-trusted peer is dropped, so request.client.host
    is the real connecting address.
    """
    if not request.client:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def get_accessible_database(database_id: int, db: Session, current_user: User) -> DatabaseAccount:
    item = db.query(DatabaseAccount).filter(DatabaseAccount.id == database_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Database not found")
    ensure_owner_access(db, current_user, item.owner_id)
    return item


@router.get("", response_model=List[DatabaseOut])
def list_databases(
    q: str = Query(default="", max_length=255),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = scope_owner(db.query(DatabaseAccount), DatabaseAccount.owner_id, db, current_user)
    search = (q or "").strip().lower()
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            DatabaseAccount.db_name.ilike(like),
            DatabaseAccount.db_user.ilike(like),
        ))
    return query.order_by(DatabaseAccount.id.desc()).all()


def ensure_database_quota(db: Session, owner: User) -> None:
    """Room for one more database: the owner's own database_limit (0 =
    unlimited; an administrator has none) and, under an overselling reseller,
    its share. Every database counts, a WordPress site's included.

    Packages carried database_limit long before anything read it; until 1.2.0
    an account could make as many databases as it liked.
    """
    if not is_admin_role(owner.role):
        limit = int(owner.database_limit or 0)
        if limit:
            owned = db.query(DatabaseAccount).filter(DatabaseAccount.owner_id == owner.id).count()
            if owned >= limit:
                raise HTTPException(
                    status_code=403,
                    detail=f"Database limit reached ({owned}/{limit}). Ask your provider to raise it.",
                )
    try:
        reseller_pool.ensure_room(db, owner, "database")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("", response_model=DatabaseCreatedOut)
def create_database(payload: DatabaseCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_name = payload.db_name
    db_user = payload.db_user or db_name
    db_password = payload.db_password or mariadb.random_password()
    ensure_database_quota(db, current_user)

    if db.query(DatabaseAccount).filter(DatabaseAccount.db_name == db_name).first():
        raise HTTPException(status_code=409, detail="Database name already exists")
    if db.query(DatabaseAccount).filter(DatabaseAccount.db_user == db_user).first():
        raise HTTPException(status_code=409, detail="Database user already exists")

    try:
        mariadb.create_database_credentials(db_name, db_user, db_password)
    except ValueError as exc:
        # A reserved account, or one that already exists in MariaDB without
        # BPanel knowing about it. Both are the caller's mistake, not a fault.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to create MariaDB database/user")
        raise HTTPException(status_code=500, detail=f"MariaDB error: {exc}") from exc

    item = DatabaseAccount(
        owner_id=current_user.id,
        db_name=db_name,
        db_user=db_user,
        db_password=encrypt(db_password),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return DatabaseCreatedOut(
        id=item.id,
        owner_id=item.owner_id,
        website_id=item.website_id,
        db_name=item.db_name,
        db_user=item.db_user,
        db_password=db_password,
    )


@router.patch("/{database_id}/owner", response_model=DatabaseOut)
def assign_database(
    database_id: int,
    payload: DatabaseOwnerUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Give a database to another panel user (administrators).

    Panel ownership only: the database, its MariaDB user and its password stay
    as they are, so whatever connects to it keeps working; the new owner sees,
    backs up and manages it in their panel. Websites and applications could
    change hands while their database could not (160.236.192.120, 2026-10-02).
    One linked to a website goes with that website instead.
    """
    ensure_role(current_user.role, Role.admin)
    item = db.query(DatabaseAccount).filter(DatabaseAccount.id == database_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Database not found")
    owner = db.query(User).filter(User.id == payload.owner_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="User not found")
    if item.website_id:
        site = db.query(Website).filter(Website.id == item.website_id).first()
        if site is not None and site.owner_id != owner.id:
            raise HTTPException(
                status_code=409,
                detail=f"{item.db_name} belongs to the website {site.domain}. Assign the website to "
                       f"{owner.username} and the database goes with it.",
            )
    previous = item.owner.username if item.owner else str(item.owner_id)
    item.owner_id = owner.id
    db.commit()
    db.refresh(item)
    log_action(db, current_user.id, "assign_database", item.db_name,
               f"{previous} -> {owner.username}", request=request)
    return item


@router.delete("/{database_id}")
def delete_database_record(database_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = get_accessible_database(database_id, db, current_user)
    try:
        mariadb.drop_database(item.db_name, item.db_user)
    except Exception as exc:
        logger.exception("Failed to delete MariaDB database/user")
        raise HTTPException(status_code=500, detail=f"MariaDB error: {exc}") from exc
    try:
        db.delete(item)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to delete database record")
        raise HTTPException(status_code=500, detail="Panel database error") from exc
    return {"ok": True}


@router.get("/{database_id}/download")
def download_database(database_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = get_accessible_database(database_id, db, current_user)
    temp_path = None
    try:
        temp_file = NamedTemporaryFile(prefix=f"{item.db_name}-", suffix=".sql", delete=False)
        temp_file.close()
        temp_path = Path(temp_file.name)
        mariadb.export_database(item.db_name, str(temp_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        temp_path,
        filename=f"{item.db_name}.sql",
        media_type="application/sql",
        background=BackgroundTask(lambda path: path.unlink(missing_ok=True), temp_path),
    )


@router.get("/phpmyadmin-sso/{token}")
def consume_phpmyadmin_sso(token: str, request: Request):
    """Consume a one-shot phpMyAdmin SSO token.

    Security model:
      * 256-bit token entropy (secrets.token_urlsafe(32)).
      * One-shot (file removed on read), TTL 60 seconds.
      * Restricted to loopback callers. The phpMyAdmin signon script always
        curls ``http(s)://127.0.0.1:<port>/api/...`` from the same host, so a
        legitimate request never has a remote peer.
    """
    if not _is_loopback_peer(request):
        peer = request.client.host if request.client else "unknown"
        logger.warning("phpmyadmin-sso non-loopback access attempt from %s", peer)
        raise HTTPException(status_code=404, detail="Invalid or expired token")
    data = consume_phpmyadmin_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Invalid or expired token")
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@router.post("/{database_id}/phpmyadmin-sso")
def create_phpmyadmin_sso(database_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = get_accessible_database(database_id, db, current_user)
    try:
        db_password = decrypt(item.db_password)
    except RuntimeError:
        raise HTTPException(
            status_code=500,
            detail="Failed to access stored database password; please re-save the password in panel settings",
        )
    token = create_phpmyadmin_token(item.db_user, db_password, item.db_name)
    log_action(
        db,
        current_user.id,
        "phpmyadmin_sso",
        f"db={item.db_name}",
        request=request,
    )
    return {"url": f"{panel_urls.tools_base_url(request)}/phpmyadmin/bpanel-signon.php?bpanel_sso={token}"}


@router.post("/{database_id}/password")
def change_database_password(database_id: int, payload: DatabasePasswordUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = get_accessible_database(database_id, db, current_user)
    mariadb.change_database_password(item.db_user, payload.password)
    item.db_password = encrypt(payload.password)
    db.commit()
    return {"ok": True, "db_user": item.db_user}
