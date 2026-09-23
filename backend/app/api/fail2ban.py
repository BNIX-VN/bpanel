"""Who fail2ban is currently keeping out, and letting one back in.

Admin only: this is the whole server, not one account. Every route needs the
addon, so a panel where nobody asked for fail2ban answers 409 rather than
pretending the feature is simply broken.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.models.entities import User
from app.services import addons, fail2ban
from app.services.audit import log_action

router = APIRouter(prefix="/fail2ban", tags=["fail2ban"])


class UnbanRequest(BaseModel):
    ip: str


@router.get("/status")
def status(current_user: User = Depends(get_current_user)):
    """Counts and health. Deliberately not the ban list.

    The list is a separate call so the page can show a number and fetch the
    addresses only when somebody asks to see them.
    """
    ensure_role(current_user.role, Role.admin)
    addons.require(addons.FAIL2BAN)
    return fail2ban.status()


@router.get("/banned")
def banned(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    addons.require(addons.FAIL2BAN)
    try:
        return fail2ban.banned(limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/unban")
def unban(
    payload: UnbanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Let an address back in.

    The one people actually need: an admin locks themselves out from a new
    network and has to undo it from another machine.
    """
    ensure_role(current_user.role, Role.admin)
    addons.require(addons.FAIL2BAN)
    try:
        fail2ban.unban(payload.ip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "fail2ban_unban", payload.ip)
    return {"unbanned": payload.ip, **fail2ban.banned()}
