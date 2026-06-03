from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.permissions import Role, ensure_role
from app.models.entities import User
from app.services import waf

router = APIRouter(prefix="/waf", tags=["waf"])


class WafCustomRulesUpdate(BaseModel):
    content: str = ""


@router.get("/status")
def get_waf_status(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return waf.status().__dict__


@router.get("/rules")
def get_waf_rules(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    status = waf.status()
    default_rules = waf.default_rules()
    custom_rules = waf.custom_rules()
    return {
        "status": status.__dict__,
        "default_rules": default_rules.stdout,
        "custom_rules": custom_rules.stdout,
    }


@router.put("/rules/custom")
def save_waf_custom_rules(payload: WafCustomRulesUpdate, current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        result = waf.save_custom_rules(payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=(result.stderr or result.stdout or "Could not save WAF rules").strip())
    return result.__dict__


@router.post("/install")
def install_waf(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return waf.install_engine().__dict__


@router.post("/update-rules")
def update_waf_rules(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return waf.update_rules().__dict__
