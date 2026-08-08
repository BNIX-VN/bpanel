import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.entities import ApiToken, DatabaseAccount, ProvisioningAccount, User, Website
from app.services import mariadb, nginx, site_users, storage_quota, wordpress


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    raw = f"bp_{secrets.token_urlsafe(48)}"
    return raw, hash_token(raw)


def create_api_token(db: Session, name: str, scopes: str, allowed_ips: str) -> tuple[str, ApiToken]:
    raw, token_hash = generate_token()
    token = ApiToken(
        name=name,
        token_hash=token_hash,
        scopes=scopes,
        allowed_ips=allowed_ips,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return raw, token


def authenticate_token(db: Session, raw: str) -> ApiToken | None:
    token_hash = hash_token(raw)
    token = db.query(ApiToken).filter(
        ApiToken.token_hash == token_hash,
        ApiToken.is_active == True,
        ApiToken.revoked_at == None,
    ).first()
    if token:
        token.last_used_at = datetime.now(timezone.utc)
        db.commit()
    return token


def check_ip_allowed(token: ApiToken, client_ip: str) -> bool:
    allowed = (token.allowed_ips or "").strip()
    if not allowed:
        return True
    ips = {ip.strip() for ip in allowed.split(",") if ip.strip()}
    return client_ip in ips


def account_to_dict(account: ProvisioningAccount, db: Session) -> dict:
    user = account.user
    website = account.primary_website
    return {
        "external_id": account.external_id,
        "username": user.username if user else None,
        "email": user.email if user else None,
        "domain": website.domain if website else None,
        "package_id": account.package_id,
        "status": account.status,
        "panel_url": None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


def suspend_account(db: Session, account: ProvisioningAccount, reason: str = "") -> None:
    user = account.user
    if not user:
        return
    user.is_active = False
    user.token_version = (user.token_version or 0) + 1

    websites = db.query(Website).filter(Website.owner_id == user.id).all()
    for website in websites:
        website.status = "suspended"
        nginx.delete_wordpress_vhost(website.domain)
        nginx.write_vhost(
            website.domain,
            website.root_path,
            app_type="static",
            php_version=website.php_version,
            document_root=website.document_root or "public_html",
            custom_directives="# SUSPENDED",
            rewrite_mode="none",
            include_ssl=False,
        )
        if website.linux_user:
            try:
                site_users.lock_linux_user(website.linux_user)
            except Exception:
                pass

    account.status = "suspended"
    account.last_action = "suspend"
    account.last_message = reason
    db.commit()


def unsuspend_account(db: Session, account: ProvisioningAccount) -> None:
    user = account.user
    if not user:
        return
    user.is_active = True

    websites = db.query(Website).filter(Website.owner_id == user.id).all()
    for website in websites:
        website.status = "active"
        rewrite_mode = "front_controller" if website.app_type == "wordpress" else (website.nginx_rewrite_mode or "none")
        php_version = website.php_version if website.app_type in {"wordpress", "php"} else website.php_version
        php_socket = site_users.site_php_fpm_socket(website.linux_user, website.root_path, php_version) if website.app_type in {"wordpress", "php"} else None
        nginx.rewrite_vhost(
            website.domain,
            website.root_path,
            app_type=website.app_type,
            php_version=php_version,
            php_fpm_socket_override=php_socket,
            custom_directives=website.nginx_custom or "",
            document_root=website.document_root or "public_html",
            rewrite_mode=rewrite_mode,
            waf_enabled=website.waf_enabled,
            http_flood_enabled=website.http_flood_enabled,
            http_flood_config=website.http_flood_config or "",
            aliases=[a.domain for a in (website.aliases or []) if a.mode == "alias"],
            redirects=[a.domain for a in (website.aliases or []) if a.mode == "redirect"],
        )
        if website.linux_user:
            try:
                site_users.unlock_linux_user(website.linux_user)
            except Exception:
                pass

    account.status = "active"
    account.last_action = "unsuspend"
    account.last_message = ""
    db.commit()


def terminate_account(db: Session, account: ProvisioningAccount, backup: bool = True) -> list[str]:
    user = account.user
    deleted_domains = []

    if user:
        websites = db.query(Website).filter(Website.owner_id == user.id).all()
        for website in websites:
            db_item = db.query(DatabaseAccount).filter(DatabaseAccount.website_id == website.id).first()
            if db_item:
                mariadb.drop_database(db_item.db_name, db_item.db_user)
                db.delete(db_item)
            nginx.delete_wordpress_vhost(website.domain)
            wordpress.delete_wordpress(website.root_path)
            deleted_domains.append(website.domain)
            db.delete(website)

        site_users.delete_panel_user(user.username)
        db.delete(user)

    account.status = "terminated"
    account.last_action = "terminate"
    account.user_id = None
    account.primary_website_id = None
    db.commit()
    return deleted_domains
