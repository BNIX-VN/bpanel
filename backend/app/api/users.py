from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.core.security import hash_password
from app.models.entities import User
from app.schemas.schemas import UserCreate, UserOut, UserPasswordUpdate
from app.services.audit import log_action

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    if db.query(User).filter((User.username == payload.username) | (User.email == payload.email)).first():
        raise HTTPException(status_code=409, detail="User already exists")
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
    log_action(db, current_user.id, "create_user", user.username)
    return user


@router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return db.query(User).order_by(User.id.desc()).all()


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/{user_id}/password")
def update_user_password(user_id: int, payload: UserPasswordUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if user_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(payload.password)
    db.commit()
    log_action(db, current_user.id, "update_user_password", user.username)
    return {"message": f"Changed password for user {user.username}"}
