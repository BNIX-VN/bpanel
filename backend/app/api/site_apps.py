"""Application slots for a website.

Three kinds, sharing one nginx path. "proxy" only records the loopback port the
domain forwards to and leaves the process to the customer. "node" and "docker"
also make the panel own the process: it writes a systemd unit through the
privileged helper and drives start, stop and logs from there.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.models.entities import SiteApp, User, Website
from app.schemas.schemas import NodeInstallRequest, SiteAppControl, SiteAppCreate, SiteAppOut, SiteAppUpdate
from app.services import nginx, site_apps, site_users
from app.services.audit import log_action

router = APIRouter(prefix="/site-apps", tags=["site-apps"])
# Separate prefix on purpose: under /site-apps these would be shadowed by
# /{app_id}/status and answer 422 instead of dispatching here.
runtime_router = APIRouter(prefix="/site-runtimes", tags=["site-apps"])


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
        image, container_port, cpu_limit = (None, 3000, "1")
        if kind == "node":
            start_kind, start_arg = site_apps.validate_start(payload.start_kind, payload.start_arg, app_root)
            node_major = node_major or "22"
        elif kind == "docker":
            image = site_apps.validate_image(payload.image, enforce_registry=not is_admin_role(current_user.role))
            container_port = site_apps.validate_container_port(payload.container_port)
            cpu_limit = site_apps.validate_cpu_limit(payload.cpu_limit)
        env = site_apps.validate_env(payload.env)
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
        image=image,
        container_port=container_port,
        cpu_limit=cpu_limit,
        env=env,
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
        if payload.image is not None:
            app.image = site_apps.validate_image(payload.image, enforce_registry=not is_admin_role(current_user.role))
        if payload.container_port is not None:
            app.container_port = site_apps.validate_container_port(payload.container_port)
        if payload.cpu_limit is not None:
            app.cpu_limit = site_apps.validate_cpu_limit(payload.cpu_limit)
        if payload.env is not None:
            app.env = site_apps.validate_env(payload.env)
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
    # Tear the runtime down before the row goes, otherwise the unit and the
    # container outlive the record that describes them.
    try:
        site_apps.delete_runtime(website, app)
    except (RuntimeError, ValueError):
        pass
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




# --- managed runtime lifecycle ----------------------------------------------

def _managed(app: SiteApp) -> None:
    if app.kind not in site_apps.MANAGED_KINDS:
        raise HTTPException(
            status_code=400,
            detail="This application only records a proxy target. Recreate it as a Node.js or container app for BPanel to run it.",
        )


def _record_status(db: Session, app: SiteApp, status: str, error: str = "") -> None:
    app.status = status
    app.last_error = (error or "")[-2000:]
    db.commit()


@router.post("/{app_id}/deploy")
def deploy_site_app(app_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetch what the app needs, write its unit, and start it."""
    ensure_role(current_user.role, Role.end_user)
    app = _owned_app(db, current_user, app_id)
    _managed(app)
    website = db.query(Website).filter(Website.id == app.website_id).first()
    steps: list[str] = []
    try:
        if app.kind == "docker":
            steps.append(site_apps.pull_image(app))
        elif (app.app_root or "") and app.start_kind in {"npm", "npx", "yarn", "node"}:
            try:
                steps.append(site_apps.install_dependencies(website, app))
            except RuntimeError as exc:
                # No package.json is normal for a single-file entry point.
                if "no package.json" not in str(exc).lower():
                    raise
        unit = site_apps.write_runtime(website, app)
        site_apps.control(website, app, "enable" if app.autostart else "disable")
        site_apps.control(website, app, "restart")
    except (RuntimeError, ValueError) as exc:
        _record_status(db, app, "error", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    running = site_apps.is_running(website, app)
    _record_status(db, app, "running" if running else "error", "" if running else "Unit did not stay active; check the log.")
    log_action(db, current_user.id, "deploy_site_app", website.domain, f"{app.name} :{app.port}")
    return {
        "unit": unit,
        "status": app.status,
        "running": running,
        "output": "\n".join(step for step in steps if step)[-4000:],
    }


@router.post("/{app_id}/control")
def control_site_app(app_id: int, payload: SiteAppControl, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    app = _owned_app(db, current_user, app_id)
    _managed(app)
    website = db.query(Website).filter(Website.id == app.website_id).first()
    try:
        output = site_apps.control(website, app, payload.action)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    running = site_apps.is_running(website, app)
    _record_status(db, app, "running" if running else "stopped")
    log_action(db, current_user.id, f"{payload.action}_site_app", website.domain, app.name)
    return {"action": payload.action, "running": running, "status": app.status, "output": output[-2000:]}


@router.get("/{app_id}/status")
def site_app_status(app_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    app = _owned_app(db, current_user, app_id)
    website = db.query(Website).filter(Website.id == app.website_id).first()
    if app.kind not in site_apps.MANAGED_KINDS:
        return {"managed": False, "running": False, "unit": ""}
    return {
        "managed": True,
        "running": site_apps.is_running(website, app),
        "unit": site_apps.unit_name(website, app),
        "status": app.status,
        "last_error": app.last_error,
    }


@router.get("/{app_id}/logs")
def site_app_logs(app_id: int, lines: int = 200, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    app = _owned_app(db, current_user, app_id)
    _managed(app)
    website = db.query(Website).filter(Website.id == app.website_id).first()
    try:
        return {"log": site_apps.logs(website, app, lines)}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- server side runtimes (admin) -------------------------------------------

@runtime_router.get("/status")
def runtime_status(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.end_user)
    return {
        "docker": site_apps.docker_status(),
        "node_majors": site_apps.installed_node_majors(),
        "allowed_registries": list(site_apps.allowed_registries()),
    }


@runtime_router.post("/docker-install")
def runtime_install_docker(current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        output = site_apps.install_docker()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Docker is ready.", "output": output, "docker": site_apps.docker_status()}


@runtime_router.post("/node-install")
def runtime_install_node(payload: NodeInstallRequest, current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    try:
        output = site_apps.install_node(payload.major)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": f"Node {payload.major} is ready.", "output": output, "node_majors": site_apps.installed_node_majors()}
