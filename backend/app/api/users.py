from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List, Optional

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.core.security import hash_password
from app.models.entities import AuditLog, User, Website
from app.schemas.schemas import (
    AuditLogOut,
    UserCreate,
    UserOut,
    UserPasswordUpdate,
    UserUpdate,
)
from app.services.audit import log_action
from app.services import site_users, storage_quota

router = APIRouter(prefix="/users", tags=["users"])


def _user_out(user: User, db: Session) -> dict:
    data = UserOut.model_validate(user).model_dump()
    data.update(storage_quota.storage_usage_summary(db, user))
    return data


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    if db.query(User).filter((User.username == payload.username) | (User.email == payload.email)).first():
        raise HTTPException(status_code=409, detail="User already exists")
    try:
        site_users.ensure_panel_user(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        website_limit=payload.website_limit,
        storage_limit_mb=payload.storage_limit_mb,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, current_user.id, "create_user", user.username, request=request)
    return _user_out(user, db)


@router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return [_user_out(user, db) for user in db.query(User).order_by(User.id.desc()).all()]


@router.get("/me", response_model=UserOut)
def me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _user_out(current_user, db)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role_changed = False
    if payload.role is not None and payload.role != user.role:
        if user_id == current_user.id:
            raise HTTPException(status_code=400, detail="Cannot change your own role")
        user.role = payload.role
        role_changed = True
    if payload.email is not None and payload.email != user.email:
        if db.query(User).filter(User.email == payload.email, User.id != user_id).first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = payload.email
    if payload.is_active is not None:
        if user_id == current_user.id and payload.is_active is False:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        if user.is_active != payload.is_active:
            user.is_active = payload.is_active
            user.token_version = (user.token_version or 0) + 1
    if payload.website_limit is not None:
        user.website_limit = payload.website_limit
    if payload.storage_limit_mb is not None:
        user.storage_limit_mb = payload.storage_limit_mb

    if role_changed:
        # New role -> existing tokens with old role claim should be invalidated.
        user.token_version = (user.token_version or 0) + 1

    db.commit()
    db.refresh(user)
    log_action(db, current_user.id, "update_user", user.username, request=request)
    return _user_out(user, db)


@router.delete("/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    site_count = db.query(Website).filter(Website.owner_id == user.id).count()
    if site_count:
        raise HTTPException(
            status_code=400,
            detail=f"User owns {site_count} website(s); reassign them before deletion",
        )
    db.delete(user)
    db.commit()
    log_action(db, current_user.id, "delete_user", user.username, request=request)
    return {"ok": True}


@router.post("/{user_id}/password")
def update_user_password(user_id: int, payload: UserPasswordUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if user_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(payload.password)
    # Force re-login on all other sessions of this user.
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    log_action(db, current_user.id, "update_user_password", user.username, request=request)
    return {"message": f"Changed password for user {user.username}"}


@router.post("/{user_id}/2fa/reset")
def reset_user_two_factor(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Use the Security page to disable your own 2FA")
    user.totp_enabled = False
    user.totp_secret = None
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    log_action(db, current_user.id, "reset_user_2fa", user.username, request=request)
    return {"message": f"Reset 2FA for user {user.username}"}


@router.get("/audit/log", response_model=List[AuditLogOut])
def list_audit(
    user_id: Optional[int] = Query(default=None),
    action: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    query = db.query(AuditLog).order_by(AuditLog.id.desc())
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    rows = query.offset(offset).limit(limit).all()
    return [AuditLogOut.from_row(row) for row in rows]
