from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_admin_role
from app.core.secrets import encrypt
from app.models.entities import DatabaseAccount, User, Website
from app.schemas.schemas import WebsiteCreate, WebsiteLogOut, WebsiteNginxConfig, WebsiteNginxCustom, WebsiteOut, WebsiteUpdate, WebsiteWafUpdate
from app.services import mariadb, nginx, site_users, ssl, storage_quota, wordpress
from app.services.audit import log_action

_PLACEHOLDER_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "nginx"

router = APIRouter(prefix="/websites", tags=["websites"])


def _command_error(result):
    return (result.stderr or result.stdout or f"Command failed with code {result.returncode}").strip()


def _cleanup_failed_site(root_path: str, linux_user: str | None, delete_files: bool = True) -> None:
    if delete_files:
        try:
            wordpress.delete_wordpress(root_path)
        except Exception:
            pass


@router.post("", response_model=WebsiteOut)
def create_website(payload: WebsiteCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a website. If install_wordpress is False, only creates the domain
    folder + Nginx vhost (no DB, no WordPress files)."""
    requested_owner_id = payload.owner_id
    if requested_owner_id is not None and requested_owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    if db.query(Website).filter(Website.domain == payload.domain).first():
        raise HTTPException(status_code=409, detail="Domain already exists")

    if requested_owner_id is not None:
        owner = db.query(User).filter(User.id == requested_owner_id).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")
    else:
        owner = current_user

    owner_id = owner.id
    current_count = db.query(Website).filter(Website.owner_id == owner_id).count()
    if not is_admin_role(owner.role) and current_count >= owner.website_limit:
        raise HTTPException(status_code=403, detail="Website limit reached")

    install_wp = payload.install_wordpress and payload.app_type == "wordpress"
    create_estimate_bytes = storage_quota.WORDPRESS_SITE_ESTIMATE_BYTES if install_wp else storage_quota.STATIC_SITE_ESTIMATE_BYTES
    try:
        storage_quota.enforce_user_storage_quota(db, owner, incoming_bytes=create_estimate_bytes)
    except storage_quota.StorageQuotaExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    linux_user = site_users.linux_user_for_panel_username(owner.username)
    root_path = site_users.site_root_for_panel_user(owner.username, payload.domain)
    if install_wp and (not payload.admin_email or not payload.admin_password):
        raise HTTPException(status_code=400, detail="admin_email and admin_password are required when install_wordpress is true")

    if install_wp:
        db_info = mariadb.create_database(payload.domain)
        try:
            linux_user = site_users.ensure_site_runtime(payload.domain, root_path, payload.php_version, linux_user)
            root_path = wordpress.install_wordpress(
                payload.domain,
                db_info,
                payload.title,
                payload.admin_user,
                payload.admin_password,
                str(payload.admin_email),
                payload.php_version,
                linux_user,
                root_path=root_path,
            )
        except (RuntimeError, ValueError) as exc:
            mariadb.drop_database(db_info["db_name"], db_info["db_user"])
            _cleanup_failed_site(root_path, linux_user)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            nginx.write_vhost(
                payload.domain,
                root_path,
                app_type="wordpress",
                php_version=payload.php_version,
                php_fpm_socket_override=site_users.php_fpm_socket(linux_user, payload.php_version),
            )
        except (RuntimeError, ValueError) as exc:
            mariadb.drop_database(db_info["db_name"], db_info["db_user"])
            _cleanup_failed_site(root_path, linux_user)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_type_value = "wordpress"
    else:
        app_type_value = "php" if payload.app_type == "wordpress" else payload.app_type
        runtime_php_version = payload.php_version if app_type_value in {"wordpress", "php"} else None
        try:
            linux_user = site_users.ensure_site_runtime(payload.domain, root_path, runtime_php_version, linux_user)
            # Just create the public/ folder skeleton and write a vhost.
            public = Path(root_path) / "public"
            if not settings.command_dry_run:
                placeholder = public / "index.html"
                if not placeholder.exists():
                    env = Environment(loader=FileSystemLoader(_PLACEHOLDER_TEMPLATE_DIR), autoescape=False)
                    tmpl = env.get_template("placeholder.html.j2")
                    placeholder.write_text(tmpl.render(domain=payload.domain), encoding="utf-8")
                site_users.fix_site_path(str(public), linux_user)
            nginx.write_vhost(
                payload.domain,
                root_path,
                app_type=app_type_value,
                php_version=payload.php_version,
                php_fpm_socket_override=site_users.php_fpm_socket(linux_user, payload.php_version) if runtime_php_version else None,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            _cleanup_failed_site(root_path, linux_user)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db_info = None

    website = Website(
        domain=payload.domain,
        owner_id=owner_id,
        root_path=root_path,
        linux_user=linux_user,
        php_version=payload.php_version,
        app_type=app_type_value,
        status="active",
    )
    db.add(website)
    db.commit()
    db.refresh(website)
    if db_info:
        # Store password encrypted; phpMyAdmin SSO decrypts on demand.
        db.add(DatabaseAccount(
            website_id=website.id,
            db_name=db_info["db_name"],
            db_user=db_info["db_user"],
            db_password=encrypt(db_info["db_password"]),
        ))
        db.commit()
    log_action(
        db,
        current_user.id,
        "create_wordpress" if install_wp else "create_site",
        payload.domain,
        request=request,
    )
    return website


@router.post("/wordpress", response_model=WebsiteOut)
def create_wordpress(payload: WebsiteCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Legacy endpoint for backwards compatibility. Forces install_wordpress=True."""
    payload = payload.model_copy(update={"install_wordpress": True, "app_type": "wordpress"})
    return create_website(payload, request, db, current_user)


@router.get("", response_model=List[WebsiteOut])
def list_websites(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if is_admin_role(current_user.role):
        return db.query(Website).order_by(Website.id.desc()).all()
    return db.query(Website).filter(Website.owner_id == current_user.id).order_by(Website.id.desc()).all()


@router.patch("/{website_id}", response_model=WebsiteOut)
def update_website(website_id: int, payload: WebsiteUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    if payload.php_version is not None:
        try:
            runtime_php_version = payload.php_version if (website.app_type or "wordpress") in {"wordpress", "php"} else None
            if website.linux_user and runtime_php_version:
                site_users.ensure_site_runtime(website.domain, website.root_path, payload.php_version, website.linux_user)
            php_fpm_socket_override = site_users.php_fpm_socket(website.linux_user, payload.php_version) if runtime_php_version else None
            nginx.rewrite_vhost(
                website.domain,
                website.root_path,
                app_type=website.app_type or "wordpress",
                php_version=payload.php_version,
                custom_directives=website.nginx_custom or "",
                php_fpm_socket_override=php_fpm_socket_override,
                waf_enabled=website.waf_enabled,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Cannot write Nginx config: {exc}") from exc
        website.php_version = payload.php_version
    if payload.status is not None:
        website.status = payload.status
    if payload.owner_id is not None:
        ensure_role(current_user.role, Role.admin)
        owner = db.query(User).filter(User.id == payload.owner_id).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")
        assigned_count = db.query(Website).filter(Website.owner_id == owner.id, Website.id != website.id).count()
        if not is_admin_role(owner.role) and assigned_count >= owner.website_limit:
            raise HTTPException(status_code=403, detail="Website limit reached")
        if payload.owner_id != website.owner_id:
            try:
                storage_quota.enforce_user_storage_quota(
                    db,
                    owner,
                    incoming_bytes=storage_quota.website_storage_used_bytes(website),
                )
                new_linux_user = site_users.linux_user_for_panel_username(owner.username)
                new_root_path = site_users.site_root_for_panel_user(owner.username, website.domain)
                runtime_php_version = website.php_version if (website.app_type or "wordpress") in {"wordpress", "php"} else None
                site_users.move_site_runtime(website.root_path, new_root_path, new_linux_user, runtime_php_version)
                nginx.rewrite_vhost(
                    website.domain,
                    new_root_path,
                    app_type=website.app_type or "wordpress",
                    php_version=website.php_version,
                    custom_directives=website.nginx_custom or "",
                    php_fpm_socket_override=site_users.php_fpm_socket(new_linux_user, website.php_version) if runtime_php_version else None,
                    waf_enabled=website.waf_enabled,
                )
                website.root_path = new_root_path
                website.linux_user = new_linux_user
            except storage_quota.StorageQuotaExceeded as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        website.owner_id = payload.owner_id
    if payload.nginx_custom is not None:
        ensure_role(current_user.role, Role.admin)
        try:
            nginx.update_custom_block(website.domain, payload.nginx_custom)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        website.nginx_custom = payload.nginx_custom
    if payload.waf_enabled is not None:
        ensure_role(current_user.role, Role.admin)
        try:
            nginx.update_waf_block(website.domain, payload.waf_enabled)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        website.waf_enabled = payload.waf_enabled
    db.commit()
    db.refresh(website)
    log_action(db, current_user.id, "update_website", website.domain)
    return website


@router.get("/{website_id}/nginx-custom", response_model=WebsiteNginxCustom)
def get_website_nginx_custom(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    return WebsiteNginxCustom(nginx_custom=website.nginx_custom or "")


@router.get("/{website_id}/nginx-config", response_model=WebsiteNginxConfig)
def get_website_nginx_config(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    try:
        return WebsiteNginxConfig(nginx_config=nginx.read_vhost_config(website.domain))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{website_id}/nginx-config", response_model=WebsiteOut)
def set_website_nginx_config(website_id: int, payload: WebsiteNginxConfig, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    try:
        nginx.update_full_config(website.domain, payload.nginx_config)
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_action(db, current_user.id, "update_nginx_config", website.domain, request=request)
    return website


@router.post("/{website_id}/nginx-config/reset", response_model=WebsiteOut)
def reset_website_nginx_config(website_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    app_type = website.app_type or "wordpress"
    runtime_php_version = website.php_version if app_type in {"wordpress", "php"} else None
    try:
        nginx.rewrite_vhost(
            website.domain,
            website.root_path,
            app_type=app_type,
            php_version=website.php_version,
            custom_directives="",
            php_fpm_socket_override=site_users.php_fpm_socket(website.linux_user, website.php_version) if runtime_php_version else None,
            waf_enabled=website.waf_enabled,
        )
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    website.nginx_custom = ""
    db.commit()
    db.refresh(website)
    log_action(db, current_user.id, "reset_nginx_config", website.domain, request=request)
    return website


@router.patch("/{website_id}/waf", response_model=WebsiteOut)
def set_website_waf(website_id: int, payload: WebsiteWafUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    try:
        nginx.update_waf_block(website.domain, payload.waf_enabled)
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    website.waf_enabled = payload.waf_enabled
    db.commit()
    db.refresh(website)
    log_action(db, current_user.id, "update_waf", website.domain, "enabled" if payload.waf_enabled else "disabled", request=request)
    return website


@router.get("/{website_id}/logs", response_model=WebsiteLogOut)
def get_website_log(
    website_id: int,
    kind: str = Query(default="access", pattern="^(access|error)$"),
    lines: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    try:
        return nginx.read_site_log(website.domain, kind, lines)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{website_id}/nginx-custom", response_model=WebsiteOut)
def set_website_nginx_custom(website_id: int, payload: WebsiteNginxCustom, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Only admins can modify nginx config; the directives we accept are
    # filesystem-write-adjacent and easy to misuse.
    ensure_role(current_user.role, Role.admin)
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    try:
        nginx.update_custom_block(website.domain, payload.nginx_custom)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    website.nginx_custom = payload.nginx_custom
    db.commit()
    db.refresh(website)
    log_action(db, current_user.id, "update_nginx_custom", website.domain, request=request)
    return website


@router.delete("/{website_id}")
def delete_website(website_id: int, request: Request, delete_files: bool = True, delete_database: bool = True, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    db_item = db.query(DatabaseAccount).filter(DatabaseAccount.website_id == website.id).first()
    if delete_database and db_item:
        mariadb.drop_database(db_item.db_name, db_item.db_user)
    nginx.delete_wordpress_vhost(website.domain)
    if delete_files:
        wordpress.delete_wordpress(website.root_path)
    if db_item:
        db.delete(db_item)
    db.delete(website)
    db.commit()
    log_action(db, current_user.id, "delete_website", website.domain, request=request)
    return {"ok": True}


@router.post("/{website_id}/fix-nginx-security")
def fix_nginx_security(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    target = nginx.harden_existing_wordpress_vhost(
        website.domain,
        website.root_path,
        website.php_version,
        php_fpm_socket_override=site_users.php_fpm_socket(website.linux_user, website.php_version),
        waf_enabled=website.waf_enabled,
    )
    log_action(db, current_user.id, "fix_nginx_security", website.domain)
    return {"message": f"Rewrote Nginx security template for {website.domain}", "path": target}


@router.post("/{website_id}/ssl", response_model=WebsiteOut)
def enable_ssl(website_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    if website.owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    result = ssl.issue_ssl(website.domain)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=_command_error(result))
    website.ssl_enabled = True
    db.commit()
    db.refresh(website)
    log_action(db, current_user.id, "enable_ssl", website.domain)
    return website
