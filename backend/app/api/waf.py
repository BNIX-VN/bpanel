from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.permissions import Role, ensure_role
from app.models.entities import User
from app.services import waf

router = APIRouter(prefix="/waf", tags=["waf"])


@router.get("/status")
def get_waf_status(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return waf.status().__dict__


@router.post("/install")
def install_waf(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return waf.install_engine().__dict__


@router.post("/update-rules")
def update_waf_rules(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return waf.update_rules().__dict__
