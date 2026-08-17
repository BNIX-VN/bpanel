"""Application slots for a website.

Phase 1 covers the proxy half: the record says which loopback port the domain
forwards to, and writing it rewrites the vhost. Owning the process that answers
on that port lands in the node phase.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.models.entities import SiteApp, User, Website
from app.schemas.schemas import SiteAppCreate, SiteAppOut, SiteAppUpdate
from app.services import nginx, site_apps, site_users
from app.services.audit import log_action

router = APIRouter(prefix="/site-apps", tags=["site-apps"])


def _owned_website(db: Session, current_user: User, website_id: int) -> Website:
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    return website


def _owned_app(db: Session, current_user: User, app_id: int) -> SiteApp:
    app = db.query(SiteApp).filter(SiteApp.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    _owned_website(db, current_user, app.website_id)
    return app


def _sync_vhost(db: Session, website: Website) -> None:
    """Point the vhost at whatever port the website's app now uses.

    Only proxied websites care; a PHP site keeps its own template even while an
    app record exists, so switching Website mode is what flips the traffic.
    """
    if (website.app_type or "") not in nginx.PROXIED_APP_TYPES:
        return
    from app.api.websites import _rewrite_website_vhost  # circular at import time

    db.refresh(website)
    _rewrite_website_vhost(website, app_port=site_apps.app_port_for_website(website))


def _app_out(website: Website, app: SiteApp) -> dict:
    payload = SiteAppOut.model_validate(app).model_dump()
    # Where the code has to live, so the UI can say it instead of making the
    # user work it out from the website root.
    try:
        payload["directory"] = str(site_users.document_root(website.root_path, site_apps.validate_app_root(app.app_root)))
    except (ValueError, OSError):
        payload["directory"] = ""
    return payload


@router.get("/{website_id}")
def list_site_apps(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = _owned_website(db, current_user, website_id)
    owner = db.query(User).filter(User.id == website.owner_id).first() or current_user
    return {
        "items": [_app_out(website, app) for app in website.apps],
        "limit": site_apps.app_limit_for(owner),
        "used": site_apps.count_apps_for_owner(db, website.owner_id),
        "memory_ceiling_mb": site_apps.memory_ceiling_for(owner),
        "port_range": [site_apps.PORT_RANGE_START, site_apps.PORT_RANGE_END],
    }


@router.post("")
def create_site_app(payload: SiteAppCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    website = _owned_website(db, current_user, payload.website_id)
    owner = db.query(User).filter(User.id == website.owner_id).first() or current_user
    try:
        site_apps.ensure_app_quota(db, owner, is_admin_role(current_user.role))
        name = site_apps.validate_name(payload.name)
        kind = site_apps.validate_kind(payload.kind)
        app_root = site_apps.validate_app_root(payload.app_root)
        memory_limit_mb = site_apps.validate_memory_mb(
            payload.memory_limit_mb,
            None if is_admin_role(current_user.role) else site_apps.memory_ceiling_for(owner),
        )
        node_major = site_apps.validate_node_major(payload.node_major)
        start_kind, start_arg = (None, None)
        if kind == "node":
            start_kind, start_arg = site_apps.validate_start(payload.start_kind, payload.start_arg, app_root)
        port = site_apps.allocate_port(db, payload.port)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    app = SiteApp(
        website_id=website.id,
        name=name,
        kind=kind,
        app_root=app_root,
        start_kind=start_kind,
        start_arg=start_arg,
        node_major=node_major,
        port=port,
        memory_limit_mb=memory_limit_mb,
        autostart=bool(payload.autostart),
    )
    db.add(app)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An application with that name or port already exists") from exc
    db.refresh(app)

    try:
        _sync_vhost(db, website)
    except (RuntimeError, ValueError) as exc:
        db.delete(app)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Cannot write Nginx config: {exc}") from exc

    log_action(db, current_user.id, "create_site_app", website.domain, f"{name} :{port}")
    return _app_out(website, app)


@router.put("/{app_id}")
def update_site_app(app_id: int, payload: SiteAppUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    app = _owned_app(db, current_user, app_id)
    website = db.query(Website).filter(Website.id == app.website_id).first()
    owner = db.query(User).filter(User.id == website.owner_id).first() or current_user
    previous_port = app.port
    try:
        if payload.name is not None:
            app.name = site_apps.validate_name(payload.name)
        if payload.app_root is not None:
            app.app_root = site_apps.validate_app_root(payload.app_root)
        if payload.node_major is not None:
            app.node_major = site_apps.validate_node_major(payload.node_major)
        if payload.memory_limit_mb is not None:
            app.memory_limit_mb = site_apps.validate_memory_mb(
                payload.memory_limit_mb,
                None if is_admin_role(current_user.role) else site_apps.memory_ceiling_for(owner),
            )
        if payload.autostart is not None:
            app.autostart = bool(payload.autostart)
        if payload.start_kind is not None or payload.start_arg is not None:
            app.start_kind, app.start_arg = site_apps.validate_start(
                payload.start_kind or app.start_kind,
                payload.start_arg or app.start_arg,
                app.app_root,
            )
        if payload.port is not None and int(payload.port) != previous_port:
            app.port = site_apps.allocate_port(db, payload.port, exclude_app_id=app.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An application with that name or port already exists") from exc
    db.refresh(app)

    try:
        _sync_vhost(db, website)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Cannot write Nginx config: {exc}") from exc

    log_action(db, current_user.id, "update_site_app", website.domain, f"{app.name} :{app.port}")
    return _app_out(website, app)


@router.delete("/{app_id}")
def delete_site_app(app_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    app = _owned_app(db, current_user, app_id)
    website = db.query(Website).filter(Website.id == app.website_id).first()
    if (website.app_type or "") in nginx.PROXIED_APP_TYPES and len(website.apps) <= 1:
        raise HTTPException(
            status_code=400,
            detail="This website is set to proxy mode. Switch Website mode first, or the domain would have nowhere to send traffic.",
        )
    name, port = app.name, app.port
    db.delete(app)
    db.commit()
    try:
        _sync_vhost(db, website)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Cannot write Nginx config: {exc}") from exc
    log_action(db, current_user.id, "delete_site_app", website.domain, f"{name} :{port}")
    return {"deleted": name, "port": port}


@router.get("/{website_id}/suggest-port")
def suggest_port(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    _owned_website(db, current_user, website_id)
    try:
        return {"port": site_apps.allocate_port(db)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


