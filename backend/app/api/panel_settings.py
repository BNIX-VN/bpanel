from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.models.entities import User
from app.schemas.schemas import (
    MalwareScanResult,
    MalwareScanRun,
    MalwareScanStatus,
    MalwareScanToggle,
    PanelSettingsOut,
    PanelSettingsUpdate,
    PanelSslInstall,
)
from app.services import panel_settings
from app.services.audit import log_action


router = APIRouter(prefix="/panel-settings", tags=["panel-settings"])


@router.get("/public", response_model=PanelSettingsOut)
def public_panel_settings():
    return panel_settings.current_settings()


@router.get("", response_model=PanelSettingsOut)
def get_panel_settings(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return panel_settings.current_settings()


@router.patch("", response_model=PanelSettingsOut)
def update_panel_settings(
    payload: PanelSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    try:
        result = panel_settings.update_settings(
            payload.app_name,
            payload.panel_hostname,
            payload.panel_port,
            payload.panel_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    log_action(db, current_user.id, "update_panel_settings", result.get("panel_url") or "panel", request=request)
    return result


@router.post("/logo", response_model=PanelSettingsOut)
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    try:
        result = await panel_settings.save_asset("logo", file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "upload_panel_logo", "panel", request=request)
    return result


@router.post("/favicon", response_model=PanelSettingsOut)
async def upload_favicon(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    try:
        result = await panel_settings.save_asset("favicon", file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "upload_panel_favicon", "panel", request=request)
    return result


@router.post("/ssl", response_model=PanelSettingsOut)
def install_panel_ssl(
    payload: PanelSslInstall,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    try:
        result = panel_settings.install_panel_ssl(
            str(payload.email or ""),
            panel_hostname=payload.panel_hostname,
            panel_port=payload.panel_port,
            panel_url=payload.panel_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    log_action(db, current_user.id, "install_panel_ssl", result.get("panel_url") or payload.panel_hostname or "panel", request=request)
    return result


@router.get("/malware-scan", response_model=MalwareScanStatus)
def get_malware_scan_status(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return panel_settings.malware_scan_status()


@router.post("/malware-scan/toggle", response_model=PanelSettingsOut)
def toggle_malware_scan(
    payload: MalwareScanToggle,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    try:
        result = panel_settings.set_malware_scan(payload.enabled)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    action = "enable_malware_scan" if payload.enabled else "disable_malware_scan"
    log_action(db, current_user.id, action, "malware-scan", request=request)
    return result


@router.post("/malware-scan/run", response_model=MalwareScanResult)
def run_malware_scan(
    payload: MalwareScanRun,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    try:
        result = panel_settings.run_scan(payload.website_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    log_action(db, current_user.id, "malware_scan_run", str(payload.website_id), request=request)
    return result
