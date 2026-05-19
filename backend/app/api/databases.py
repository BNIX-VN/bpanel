from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.core.secrets import decrypt, encrypt
from app.models.entities import DatabaseAccount, User, Website
from app.schemas.schemas import DatabaseOut, DatabasePasswordUpdate
from app.services import mariadb
from app.services.sso_tokens import consume_phpmyadmin_token, create_phpmyadmin_token

router = APIRouter(prefix="/databases", tags=["databases"])


def get_accessible_database(database_id: int, db: Session, current_user: User) -> DatabaseAccount:
    item = db.query(DatabaseAccount).filter(DatabaseAccount.id == database_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Database not found")
    website = db.query(Website).filter(Website.id == item.website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    return item


@router.get("", response_model=List[DatabaseOut])
def list_databases(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(DatabaseAccount).join(Website)
    if current_user.role not in {"super_admin", "admin"}:
        query = query.filter(Website.owner_id == current_user.id)
    return query.order_by(DatabaseAccount.id.desc()).all()


@router.delete("/{database_id}")
def delete_database_record(database_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    item = db.query(DatabaseAccount).filter(DatabaseAccount.id == database_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Database not found")
    mariadb.drop_database(item.db_name, item.db_user)
    db.delete(item)
    db.commit()
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
def consume_phpmyadmin_sso(token: str):
    """Consume a one-shot phpMyAdmin SSO token.

    Security model: 256-bit token entropy (secrets.token_urlsafe(32)), one-shot
    (file removed on read), TTL 60 seconds. The previous IP whitelist was a
    no-op because uvicorn was not configured with proxy headers, so we now
    rely entirely on token secrecy.
    """
    data = consume_phpmyadmin_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Invalid or expired token")
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@router.post("/{database_id}/phpmyadmin-sso")
def create_phpmyadmin_sso(database_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = get_accessible_database(database_id, db, current_user)
    token = create_phpmyadmin_token(item.db_user, decrypt(item.db_password), item.db_name)
    return {"url": f"/phpmyadmin/bpanel-signon.php?bpanel_sso={token}"}


@router.post("/{database_id}/password")
def change_database_password(database_id: int, payload: DatabasePasswordUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = get_accessible_database(database_id, db, current_user)
    mariadb.change_database_password(item.db_user, payload.password)
    item.db_password = encrypt(payload.password)
    db.commit()
    return {"ok": True, "db_user": item.db_user}
