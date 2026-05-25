import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import Role, ensure_role
from app.core.secrets import encrypt
from app.core.security import hash_password
from app.models.entities import DatabaseAccount, User, Website
from app.schemas.schemas import WebsiteCreate, WebsiteNginxCustom, WebsiteOut, WebsiteUpdate
from app.services import mariadb, nginx, site_users, ssl, wordpress
from app.services.audit import log_action

router = APIRouter(prefix="/websites", tags=["websites"])


def _panel_email_for_site_user(username: str) -> str:
    return f"{username}@users.bpanel.vn"


def _ensure_panel_user_for_site(db: Session, username: str) -> tuple[User, str | None]:
    user = db.query(User).filter(User.username == username).first()
    if user:
        return user, None

    password = secrets.token_urlsafe(18)
    email = _panel_email_for_site_user(username)
    if db.query(User).filter(User.email == email).first():
        email = f"{username}-{secrets.token_hex(4)}@users.bpanel.test"
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role="user",
        website_limit=1,
        storage_limit_mb=1024,
    )
    db.add(user)
    db.flush()
    return user, password


def _website_out_with_panel_user(website: Website, username: str | None, password: str | None) -> WebsiteOut:
    out = WebsiteOut.model_validate(website)
    if username:
        out.panel_username = username
    if password:
        out.panel_password = password
    return out


def _delete_auto_panel_user_for_site(db: Session, website: Website, current_user: User) -> None:
    owner = website.owner
    if not owner or owner.id == current_user.id:
        return
    if not website.linux_user or owner.username != website.linux_user:
        return
    if owner.role != "user" or not owner.email.endswith(("@users.bpanel.vn", "@users.bpanel.test")):
        return
    remaining = db.query(Website).filter(Website.owner_id == owner.id, Website.id != website.id).count()
    if remaining == 0:
        db.delete(owner)


def _command_error(result):
    return (result.stderr or result.stdout or f"Command failed with code {result.returncode}").strip()


def _cleanup_failed_site(root_path: str, linux_user: str | None, delete_files: bool = True) -> None:
    try:
        site_users.delete_site_runtime(root_path, linux_user)
    except Exception:
        pass
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
    if requested_owner_id and requested_owner_id != current_user.id:
        ensure_role(current_user.role, Role.admin)
    if db.query(Website).filter(Website.domain == payload.domain).first():
        raise HTTPException(status_code=409, detail="Domain already exists")

    panel_username = None
    panel_password = None
    if requested_owner_id:
        owner = db.query(User).filter(User.id == requested_owner_id).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")
    elif current_user.role in {"super_admin", "admin"}:
        panel_username = site_users.linux_user_for_domain(payload.domain)
        owner, panel_password = _ensure_panel_user_for_site(db, panel_username)
    else:
        owner = current_user

    owner_id = owner.id
    current_count = db.query(Website).filter(Website.owner_id == owner_id).count()
    if current_count >= owner.website_limit:
        raise HTTPException(status_code=403, detail="Website limit reached")

    install_wp = payload.install_wordpress and payload.app_type == "wordpress"
    root_path = site_users.site_root_for_domain(payload.domain)
    if install_wp and (not payload.admin_email or not payload.admin_password):
        raise HTTPException(status_code=400, detail="admin_email and admin_password are required when install_wordpress is true")
    linux_user = None

    if install_wp:
        db_info = mariadb.create_database(payload.domain)
        try:
            linux_user = site_users.ensure_site_runtime(payload.domain, root_path, payload.php_version)
            root_path = wordpress.install_wordpress(
                payload.domain,
                db_info,
                payload.title,
                payload.admin_user,
                payload.admin_password,
                str(payload.admin_email),
                payload.php_version,
                linux_user,
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
                php_fpm_socket_override=site_users.php_fpm_socket(linux_user),
            )
        except (RuntimeError, ValueError) as exc:
            mariadb.drop_database(db_info["db_name"], db_info["db_user"])
            _cleanup_failed_site(root_path, linux_user)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_type_value = "wordpress"
    else:
        runtime_php_version = payload.php_version if payload.app_type == "wordpress" else None
        try:
            linux_user = site_users.ensure_site_runtime(payload.domain, root_path, runtime_php_version)
            # Just create the public/ folder skeleton and write a vhost.
            public = Path(root_path) / "public"
            if not settings.command_dry_run:
                placeholder = public / "index.html"
                if not placeholder.exists():
                    placeholder.write_text(
                        f"<!doctype html><html><body><h1>{payload.domain}</h1>"
                        "<p>Site created by BPanel. Upload your files to the public folder.</p>"
                        "</body></html>",
                        encoding="utf-8",
                    )
                site_users.fix_site_path(str(public), linux_user)
            nginx.write_vhost(
                payload.domain,
                root_path,
                app_type=payload.app_type,
                php_version=payload.php_version,
                php_fpm_socket_override=site_users.php_fpm_socket(linux_user) if runtime_php_version else None,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            _cleanup_failed_site(root_path, linux_user)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db_info = None
        app_type_value = payload.app_type

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
    return _website_out_with_panel_user(website, panel_username, panel_password)


@router.post("/wordpress", response_model=WebsiteOut)
def create_wordpress(payload: WebsiteCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Legacy endpoint for backwards compatibility. Forces install_wordpress=True."""
    payload = payload.model_copy(update={"install_wordpress": True, "app_type": "wordpress"})
    return create_website(payload, request, db, current_user)


@router.get("", response_model=List[WebsiteOut])
def list_websites(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role in {"super_admin", "admin"}:
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
            if website.linux_user and (website.app_type or "wordpress") == "wordpress":
                site_users.ensure_site_runtime(website.domain, website.root_path, payload.php_version)
            php_fpm_socket_override = site_users.php_fpm_socket(website.linux_user)
            nginx.rewrite_vhost(
                website.domain,
                website.root_path,
                app_type=website.app_type or "wordpress",
                php_version=payload.php_version,
                custom_directives=website.nginx_custom or "",
                php_fpm_socket_override=php_fpm_socket_override,
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
        website.owner_id = payload.owner_id
    if payload.nginx_custom is not None:
        ensure_role(current_user.role, Role.admin)
        try:
            nginx.update_custom_block(website.domain, payload.nginx_custom)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        website.nginx_custom = payload.nginx_custom
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
        site_users.delete_site_runtime(website.root_path, website.linux_user)
    if db_item:
        db.delete(db_item)
    _delete_auto_panel_user_for_site(db, website, current_user)
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
        php_fpm_socket_override=site_users.php_fpm_socket(website.linux_user),
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
