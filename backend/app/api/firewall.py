from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.permissions import Role, ensure_role
from app.models.entities import User
from app.schemas.schemas import FirewallIpRule, FirewallPortRule
from app.services import firewall

router = APIRouter(prefix="/firewall", tags=["firewall"])


def _require_admin(current_user: User) -> None:
    ensure_role(current_user.role, Role.admin)


def _result(result):
    return result.__dict__


def _status_result(result):
    data = _result(result)
    data["rules"] = firewall.parse_numbered_rules(result.stdout)
    return data


@router.get("/status")
def get_status(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    return _status_result(firewall.status())


@router.post("/enable")
def enable_firewall(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    return _result(firewall.enable())


@router.post("/disable")
def disable_firewall(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    return _result(firewall.disable())


@router.post("/reload")
def reload_firewall(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    return _result(firewall.reload())


@router.post("/allow-port")
def allow_port(payload: FirewallPortRule, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        result = firewall.allow_port(payload.port, payload.protocol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result(result)


@router.post("/allow-ip")
def allow_ip(payload: FirewallIpRule, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        result = firewall.allow_ip(payload.ip, payload.port, payload.protocol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result(result)


@router.post("/block-ip")
def block_ip(payload: FirewallIpRule, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        result = firewall.block_ip(payload.ip, payload.port, payload.protocol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result(result)


@router.delete("/rules/{number}")
def delete_rule(number: int, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        result = firewall.delete_rule(number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result(result)
