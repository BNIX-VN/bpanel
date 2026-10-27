"""Redis per account addon: an account's own Redis, on and off by the customer.

Every route acts for the signed-in account. An administrator or a reseller
turns a customer's Redis on by logging in as the customer, as with the
terminal; the administrator's own view is the list of accounts. A demo
session reads only (demo_mode.enforce refuses its POSTs).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.addons import _install_failure
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.models.entities import User
from app.services import redis_accounts
from app.services.audit import log_action

router = APIRouter(prefix="/redis", tags=["redis"])


def _refuse(reason: str) -> None:
    code = status.HTTP_409_CONFLICT if reason == "not-installed" else status.HTTP_403_FORBIDDEN
    raise HTTPException(status_code=code, detail=redis_accounts.PROBLEM_TEXT[reason])


def _require_allowed(user: User) -> None:
    """Installed, a hosting account, not suspended, and its package allows it."""
    reason = redis_accounts.problem(user)
    if reason:
        _refuse(reason)


@router.get("")
def get_redis(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    return redis_accounts.view(current_user)


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Which accounts have their Redis on, and how big it may be."""
    ensure_role(current_user.role, Role.admin)
    if not redis_accounts.installed():
        _refuse("not-installed")
    return {"items": redis_accounts.accounts(db)}


@router.post("/enable")
def enable_redis(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    _require_allowed(current_user)
    was_on = bool(current_user.redis_enabled)
    current_user.redis_enabled = True
    db.commit()
    try:
        redis_accounts.apply(current_user)
    except RuntimeError as exc:
        # Not on if it did not start: the switch says what is running.
        current_user.redis_enabled = was_on
        db.commit()
        raise HTTPException(status_code=400, detail=_install_failure(exc)) from exc
    log_action(db, current_user.id, "redis_enable", current_user.username,
               f"{redis_accounts.limit_mb(current_user)} MB", request=request)
    return redis_accounts.view(current_user)


@router.post("/disable")
def disable_redis(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Allowed whatever the package says: turning it off is never refused."""
    ensure_role(current_user.role, Role.end_user)
    reason = redis_accounts.problem(current_user)
    if reason in ("not-installed", "admin", "no-linux-user"):
        _refuse(reason)
    current_user.redis_enabled = False
    db.commit()
    try:
        redis_accounts.remove(redis_accounts.linux_user(current_user))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=_install_failure(exc)) from exc
    log_action(db, current_user.id, "redis_disable", current_user.username, request=request)
    return redis_accounts.view(current_user)


@router.post("/flush")
def flush_redis(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Empty the account's Redis (FLUSHALL), as the account's own user."""
    ensure_role(current_user.role, Role.end_user)
    _require_allowed(current_user)
    if not current_user.redis_enabled:
        raise HTTPException(status_code=400, detail="Redis is off for this account.")
    try:
        redis_accounts.flush(current_user)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=_install_failure(exc)) from exc
    log_action(db, current_user.id, "redis_flush", current_user.username, request=request)
    return redis_accounts.view(current_user)
