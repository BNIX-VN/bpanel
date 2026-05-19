from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.permissions import Role, ensure_role
from app.models.entities import User
from app.schemas.schemas import ServiceAction
from app.services.system import install_wordpress_stack, service_action, system_info

router = APIRouter(prefix="/services", tags=["services"])


@router.get("/system-info")
def get_system_info(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.readonly)
    return system_info()


@router.post("/action")
def run_service_action(payload: ServiceAction, current_user: User = Depends(get_current_user)):
    minimum_role = Role.readonly if payload.action == "status" else Role.admin
    ensure_role(current_user.role, minimum_role)
    if payload.name == "nginx" and payload.action == "stop":
        raise HTTPException(status_code=400, detail="Stopping Nginx from the panel is disabled because it would disconnect the panel. Use restart or reload instead.")
    try:
        result = service_action(payload.name, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.__dict__


@router.post("/install-wordpress-stack")
def install_stack(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.super_admin)
    result = install_wordpress_stack()
    return result.__dict__
