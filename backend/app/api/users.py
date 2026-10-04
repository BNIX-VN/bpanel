import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload
from typing import List, Optional

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.access import managed_user
from app.core.permissions import Role, ensure_role, is_admin_role, is_reseller_role
from app.core.security import hash_password
from app.core.step_up import require_sensitive_action_step_up
from app.models.entities import AuditLog, BackupSchedule, DatabaseAccount, McpToken, User, UserPackage, Website
from app.schemas.schemas import (
    GROUP_LIMIT_FIELDS,
    RESOURCE_LIMIT_FIELDS,
    AuditLogOut,
    UserCreate,
    UserOut,
    SftpPasswordUpdate,
    UserPasswordUpdate,
    UserUpdate,
)
from app.services.audit import log_action
from app.services import demo_mode, mail, mariadb, nginx, reseller as reseller_pool, resource_limits, site_users, ssl, storage_quota, teardown, waf, wordpress

router = APIRouter(prefix="/users", tags=["users"])


def _user_out(user: User, db: Session, *, cached_usage: bool = False) -> dict:
    data = UserOut.model_validate(user).model_dump()
    data["package_name"] = user.package.name if user.package else None
    data.update(storage_quota.storage_usage_summary(db, user, use_cache=cached_usage))
    return data


def _package_for_payload(db: Session, package_id: int | None, actor: User | None = None) -> UserPackage | None:
    """The package, if ``actor`` may assign it: a reseller only its own."""
    if package_id is None:
        return None
    query = db.query(UserPackage).filter(UserPackage.id == package_id)
    if actor is not None and is_reseller_role(actor.role):
        query = query.filter(UserPackage.owner_id == actor.id)
    package = query.first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


def _reseller(db: Session, reseller_id: int) -> User:
    owner = db.query(User).filter(User.id == reseller_id).first()
    if owner is None or not is_reseller_role(owner.role):
        raise HTTPException(status_code=400, detail="That account is not a reseller")
    return owner


def _check_pool(db: Session, reseller: User, **kwargs) -> None:
    try:
        reseller_pool.check_pool(db, reseller, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _check_grants(reseller: User, package: UserPackage | None) -> None:
    try:
        reseller_pool.check_package_grants(reseller, package)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _listed_users(db: Session, actor: User):
    """Every account for an admin; a reseller's customers for a reseller."""
    query = db.query(User).options(selectinload(User.package)).order_by(User.id.desc())
    if not is_admin_role(actor.role):
        query = query.filter(User.reseller_id == actor.id)
    return query.all()


def _apply_package_limits(user: User, package: UserPackage | None) -> None:
    user.package_id = package.id if package else None
    if package:
        user.website_limit = package.website_limit
        user.storage_limit_mb = package.storage_limit_mb
        # Assigning a package is what makes its terminal_enabled mean anything;
        # before this the flag was settable and displayed but never read.
        user.terminal_enabled = package.terminal_enabled
        user.sftp_accounts_limit = package.sftp_accounts_limit
        user.mail_accounts_limit = package.mail_accounts_limit
        user.database_limit = package.database_limit
        for field in RESOURCE_LIMIT_FIELDS:
            setattr(user, field, int(getattr(package, field) or 0))


def _decode_schedule_user_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = [item for item in raw.split(",") if item]
    if isinstance(value, int):
        value = [value]
    return [int(item) for item in value if int(item) > 0]


def _remove_user_from_backup_schedules(db: Session, user_id: int) -> None:
    for schedule in db.query(BackupSchedule).all():
        changed = False
        if schedule.user_id == user_id:
            schedule.user_id = None
            changed = True
        user_ids = _decode_schedule_user_ids(schedule.user_ids)
        if user_id in user_ids:
            user_ids = [item for item in user_ids if item != user_id]
            schedule.user_ids = json.dumps(user_ids)
            changed = True
        if changed and not schedule.all_users and schedule.user_id is None and not user_ids:
            db.delete(schedule)


def _delete_owned_website(db: Session, website: Website) -> None:
    db_item = db.query(DatabaseAccount).filter(DatabaseAccount.website_id == website.id).first()
    if db_item:
        mariadb.drop_database(db_item.db_name, db_item.db_user)
    nginx.delete_wordpress_vhost(website.domain)
    # Deleting the owner deletes the site, so its certificate goes too - left
    # behind it would keep certbot renewing a name this server no longer serves.
    ssl.release_site_certificates(db, website.domain, exclude_website_id=website.id)
    waf.remove_site_rules(website.domain)
    wordpress.delete_wordpress(website.root_path)
    if db_item:
        db.delete(db_item)
    db.delete(website)


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """A new account. A reseller's new accounts are always its own customers."""
    ensure_role(current_user.role, Role.reseller)
    role = payload.role
    reseller_id = payload.reseller_id
    pools = {field: getattr(payload, field) for field in reseller_pool.SETTINGS}
    if is_reseller_role(current_user.role):
        role, reseller_id = "end_user", current_user.id
    elif role != "end_user":
        reseller_id = None
    if role != "reseller":
        pools = dict(reseller_pool.NO_POOL)
    # Only the username has to be unique — several panel users may share one
    # contact email (a reseller managing many accounts, for example).
    if db.query(User.id).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    package = _package_for_payload(db, payload.package_id, current_user)
    # What the account will hold once its package is applied, checked against
    # the share it comes out of before anything is created.
    draft = User(website_limit=payload.website_limit, storage_limit_mb=payload.storage_limit_mb,
                 sftp_accounts_limit=payload.sftp_accounts_limit, mail_accounts_limit=payload.mail_accounts_limit,
                 database_limit=payload.database_limit, terminal_enabled=False, **pools)
    _apply_package_limits(draft, package)
    limits = reseller_pool.account_limits(draft, {"package": package})
    if reseller_id:
        owner = current_user if reseller_id == current_user.id else _reseller(db, reseller_id)
        _check_grants(owner, package)
        _check_pool(db, owner, new_account=limits)
    if role == "reseller":
        _check_pool(db, draft, changes={None: {"package": package}})
    # The Linux account gets its own secret from the start. It used to be given
    # the panel password, which put that password on port 22 behind sshd.
    sftp_password = site_users.generate_login_password()
    try:
        site_users.ensure_panel_user(payload.username, sftp_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=role,
        reseller_id=reseller_id,
        **pools,
        package_id=package.id if package else None,
        website_limit=payload.website_limit,
        storage_limit_mb=payload.storage_limit_mb,
        sftp_accounts_limit=payload.sftp_accounts_limit,
        mail_accounts_limit=payload.mail_accounts_limit,
        database_limit=payload.database_limit,
        sftp_password_set_at=datetime.utcnow(),
        # Resource limits: the account's own from whoever creates it; a group
        # cap only on a reseller, and only from the administrator.
        **{field: getattr(payload, field) for field in RESOURCE_LIMIT_FIELDS},
        **{field: (getattr(payload, field) if role == "reseller" and is_admin_role(current_user.role) else 0)
           for field in GROUP_LIMIT_FIELDS},
    )
    # After the explicit value, so a package still wins when one is assigned.
    _apply_package_limits(user, package)
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, current_user.id, "create_user", user.username, request=request)
    resource_limits.sync_in_background()
    body = _user_out(user, db)
    # Returned once, to whoever created the account. Nothing stores it.
    body["sftp_password"] = sftp_password
    return body


@router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Who the accounts are. Disk usage only if it is already known.

    Measuring an account's disk usage means walking its home directory, and on
    a cold cache that is the whole list waiting on the slowest account: 3.8
    seconds for fifteen users before a single row could be drawn. The list is
    what the page is for, so it no longer waits. Rows whose figure is not
    cached report -1, and the page asks for those separately - see
    /users/storage-usage.

    An admin sees every account; a reseller sees its customers.
    """
    ensure_role(current_user.role, Role.reseller)
    rows = []
    for user in _listed_users(db, current_user):
        data = UserOut.model_validate(user).model_dump()
        data["package_name"] = user.package.name if user.package else None
        known = storage_quota.cached_storage_used_bytes(user.id)
        limit_bytes = storage_quota.user_storage_limit_bytes(user)
        data["storage_limit_bytes"] = limit_bytes
        if known is None:
            # -1, not 0: nobody has "used nothing", and a zero would draw an
            # empty bar that looks like an answer.
            data["storage_used_bytes"] = -1
            data["storage_percent"] = 0.0
        else:
            data["storage_used_bytes"] = known
            data["storage_percent"] = (
                min(999.0, round((known / limit_bytes) * 100, 2)) if limit_bytes else 0.0
            )
        rows.append(data)
    return rows


@router.get("/storage-usage")
def storage_usage(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The figures the list deliberately did not wait for.

    Walks what it has to and fills the cache, so the next list is instant. The
    page calls this once after the rows are on screen.
    """
    ensure_role(current_user.role, Role.reseller)
    return {
        str(user.id): storage_quota.storage_usage_summary(db, user)
        for user in _listed_users(db, current_user)
    }


@router.get("/pool")
def my_pool(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """A reseller's share of the server and what it has handed out."""
    ensure_role(current_user.role, Role.reseller)
    if not is_reseller_role(current_user.role):
        raise HTTPException(status_code=400, detail="Only a reseller has a share to report")
    return reseller_pool.usage(db, current_user)


@router.get("/{user_id}/pool")
def reseller_pool_usage(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.admin)
    return reseller_pool.usage(db, _reseller(db, user_id))


@router.get("/me", response_model=UserOut)
def me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _user_out(current_user, db)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.reseller)
    user = managed_user(db, current_user, user_id)
    if not is_admin_role(current_user.role):
        if user.id == current_user.id:
            raise HTTPException(status_code=403, detail="Your own limits are set by the administrator")
        if payload.role is not None or payload.reseller_id is not None or any(
                getattr(payload, field) is not None for field in reseller_pool.SETTINGS):
            raise HTTPException(status_code=403, detail="Only the administrator can change roles or resellers")
        if any(getattr(payload, field) is not None for field in GROUP_LIMIT_FIELDS):
            raise HTTPException(status_code=403, detail="A reseller's group limits are set by the administrator")
    new_role = payload.role if payload.role is not None else user.role
    if new_role != user.role and user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    if new_role != user.role and is_reseller_role(user.role) and reseller_pool.customers(db, user):
        raise HTTPException(status_code=400, detail="This reseller still has customers: move or delete them first")

    # Where the account ends up, worked out before anything changes, so a share
    # that would not hold refuses the whole edit.
    package_change = "package_id" in payload.model_fields_set
    package = _package_for_payload(db, payload.package_id, current_user) if package_change else None
    limit_changes = {field: getattr(payload, field) for field in reseller_pool.ACCOUNT_FIELDS
                     if getattr(payload, field) is not None}
    if package_change:
        if package is not None:
            # An assigned package wins over the limits sent with it, as below.
            limit_changes.update(website_limit=package.website_limit, storage_limit_mb=package.storage_limit_mb,
                                 mail_accounts_limit=package.mail_accounts_limit,
                                 database_limit=package.database_limit)
        limit_changes["package"] = package
    pool_changes = {field: getattr(payload, field) for field in reseller_pool.SETTINGS
                    if getattr(payload, field) is not None}
    new_reseller_id = user.reseller_id
    if payload.reseller_id is not None:
        new_reseller_id = payload.reseller_id or None
    if new_role != "end_user":
        new_reseller_id = None
    if new_reseller_id:
        owner = _reseller(db, new_reseller_id)
        if package_change or new_reseller_id != user.reseller_id:
            _check_grants(owner, limit_changes.get("package", user.package))
        if new_reseller_id != user.reseller_id:
            _check_pool(db, owner, new_account=reseller_pool.account_limits(user, limit_changes))
        else:
            _check_pool(db, owner, changes={user.id: limit_changes})
    if new_role == "reseller":
        _check_pool(db, user, pool=pool_changes, changes={user.id: limit_changes})

    user.reseller_id = new_reseller_id
    if new_role == "reseller":
        for field, value in pool_changes.items():
            setattr(user, field, value)
    else:
        for field, value in reseller_pool.NO_POOL.items():
            setattr(user, field, value)
    role_changed = False
    if new_role != user.role:
        user.role = new_role
        role_changed = True
    if payload.email is not None and payload.email != user.email:
        user.email = payload.email  # emails need not be unique across panel users
    active_changed = False
    if payload.is_active is not None:
        if user_id == current_user.id and payload.is_active is False:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        if user.is_active != payload.is_active:
            user.is_active = payload.is_active
            user.token_version = (user.token_version or 0) + 1
            active_changed = True
    if package_change:
        _apply_package_limits(user, package)
    if payload.website_limit is not None:
        user.website_limit = payload.website_limit
    if payload.storage_limit_mb is not None:
        user.storage_limit_mb = payload.storage_limit_mb
    if payload.sftp_accounts_limit is not None:
        user.sftp_accounts_limit = payload.sftp_accounts_limit
    if payload.mail_accounts_limit is not None:
        user.mail_accounts_limit = payload.mail_accounts_limit
    if payload.database_limit is not None:
        user.database_limit = payload.database_limit
    for field in RESOURCE_LIMIT_FIELDS:
        if getattr(payload, field) is not None:
            setattr(user, field, getattr(payload, field))
    for field in GROUP_LIMIT_FIELDS:
        if new_role != "reseller":
            setattr(user, field, 0)
        elif getattr(payload, field) is not None:
            setattr(user, field, getattr(payload, field))
    if package:
        _apply_package_limits(user, package)

    if role_changed:
        # New role -> existing tokens with old role claim should be invalidated.
        user.token_version = (user.token_version or 0) + 1

    db.commit()
    db.refresh(user)
    if active_changed:
        # A suspended account's mailboxes keep receiving but cannot sign in.
        mail.sync_quietly(db)
    log_action(db, current_user.id, "update_user", user.username, request=request)
    # Its limits, its reseller or its role may have moved its slice.
    resource_limits.sync_in_background()
    return _user_out(user, db)


@router.delete("/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.reseller)
    user = managed_user(db, current_user, user_id)
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if is_reseller_role(user.role) and reseller_pool.customers(db, user):
        raise HTTPException(status_code=400, detail="This reseller still has customers: move or delete them first")
    websites = db.query(Website).filter(Website.owner_id == user.id).order_by(Website.id.asc()).all()
    deleted_domains = []
    panel_linux_user = site_users.linux_user_for_panel_username(user.username)
    try:
        for website in websites:
            if website.linux_user and website.linux_user != panel_linux_user:
                raise ValueError(f"Website {website.domain} is not owned by Linux user {panel_linux_user}")
        for website in websites:
            _delete_owned_website(db, website)
            deleted_domains.append(website.domain)
        _remove_user_from_backup_schedules(db, user.id)
        # Databases and applications are keyed on owner_id, not website_id, so
        # the website loop above cannot reach a database that belongs to no
        # website - which is the only kind POST /api/databases creates - nor any
        # application at all. Migrations 0014/0015 and 0025 re-parented both
        # tables onto users; nothing here followed, and the panel database does
        # not enforce the cleanup it declares (see services/teardown.py).
        purged = teardown.purge_owned_resources(db, user.id)
        # The FK declares ON DELETE CASCADE, but SQLite only honours that with
        # PRAGMA foreign_keys on, and this database does not enforce the
        # cleanup it declares - the same reason purge_owned_resources exists.
        # A leftover token row would be an orphan, not a way in (authenticate
        # refuses a token whose owner is gone), but it would still be a row
        # nobody can see or revoke.
        db.query(McpToken).filter(McpToken.user_id == user.id).delete(synchronize_session=False)
        # A reseller's own packages go with it; nobody is left on them, since
        # a reseller with customers cannot be deleted.
        for item in db.query(UserPackage).filter(UserPackage.owner_id == user.id).all():
            db.query(User).filter(User.package_id == item.id).update({User.package_id: None}, synchronize_session=False)
            db.delete(item)
        # Their mail is in the home that goes next; the rows go with it.
        mail.delete_for_owner(db, user)
        site_users.delete_panel_user(user.username)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    username = user.username
    db.delete(user)
    db.commit()
    mail.sync_quietly(db)
    detail = ",".join(deleted_domains)
    if purged["databases"] or purged["applications"]:
        # Worth recording separately: these are resources the website loop never
        # touched, so before this sweep existed they simply stayed behind.
        detail = f"{detail} +db:{len(purged['databases'])} +app:{len(purged['applications'])}"
    log_action(db, current_user.id, "delete_user", username, detail, request=request)
    resource_limits.sync_in_background()
    return {
        "ok": True,
        "deleted_websites": deleted_domains,
        "deleted_databases": purged["databases"],
        "deleted_applications": purged["applications"],
    }


@router.post("/{user_id}/password")
def update_user_password(user_id: int, payload: UserPasswordUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if user_id != current_user.id:
        ensure_role(current_user.role, Role.reseller)
    else:
        require_sensitive_action_step_up(current_user, payload.current_password, payload.code)
    user = managed_user(db, current_user, user_id)
    # The panel password no longer reaches the Linux account. It used to, which
    # meant sshd offered the panel password to the internet on port 22.
    try:
        minted = site_users.retire_shared_login_password(
            user.username, already_separate=user.sftp_password_set_at is not None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if minted is not None:
        user.sftp_password_set_at = datetime.utcnow()
    user.hashed_password = hash_password(payload.password)
    # Force re-login on all other sessions of this user.
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    log_action(db, current_user.id, "update_user_password", user.username, request=request)
    from app.services import notifications

    notifications.notify_in_background("security_change", {
        "kind": "password", "username": user.username, "when": notifications.now_text(),
    }, user_ids=[user.id])
    body = {"message": f"Changed password for user {user.username}"}
    if minted is not None:
        # This account's SFTP login was the panel password until a moment ago.
        # It has been replaced so the old value stops working, and this is the
        # only time the new one is readable.
        body["sftp_password"] = minted
        body["sftp_password_rotated"] = True
        body["message"] += (
            ". Its SFTP password was the same secret and has been replaced - "
            "copy the new one now, it is not shown again."
        )
    return body


@router.post("/{user_id}/sftp-password")
def set_sftp_password(
    user_id: int,
    payload: SftpPasswordUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set this account's SFTP password, independently of the panel password.

    Before 0033 there was no such thing: the Linux account carried whatever the
    panel password was, so sshd offered the panel password to anyone on port 22,
    and an SFTP brute force was a panel compromise - which through the sudo
    helper is root.

    Sending no password means "generate one", which is the better default: it
    is the one case where the value is guaranteed not to be a password the user
    has used somewhere else.
    """
    if user_id != current_user.id:
        ensure_role(current_user.role, Role.reseller)
    else:
        require_sensitive_action_step_up(current_user, payload.current_password, payload.code)
    user = managed_user(db, current_user, user_id)

    # Named for what it is. This is the one endpoint where a value the user
    # typed may legitimately reach chpasswd, and calling it `password` would
    # make it indistinguishable from a panel password at a glance.
    sftp_password = payload.password or site_users.generate_login_password()
    generated = payload.password is None
    try:
        site_users.set_panel_user_password(user.username, sftp_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    was_shared = user.sftp_password_set_at is None
    user.sftp_password_set_at = datetime.utcnow()
    db.commit()
    log_action(db, current_user.id, "set_sftp_password", user.username, request=request)
    return {
        "message": "SFTP password updated",
        # Returned once, and only when the panel invented it. A password the
        # user chose is never echoed back.
        "password": sftp_password if generated else None,
        # True when this call is what finally separated the two secrets.
        "separated_from_panel_password": was_shared,
    }


@router.post("/{user_id}/2fa/reset")
def reset_user_two_factor(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_role(current_user.role, Role.reseller)
    user = managed_user(db, current_user, user_id)
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Use the Security page to disable your own 2FA")
    user.totp_enabled = False
    user.totp_secret = None
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    log_action(db, current_user.id, "reset_user_2fa", user.username, request=request)
    from app.services import notifications

    notifications.notify_in_background("security_change", {
        "kind": "2fa_reset", "username": user.username, "when": notifications.now_text(),
    }, user_ids=[user.id])
    return {"message": f"Reset 2FA for user {user.username}"}

@router.post("/{user_id}/suspend")
def suspend_user(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Full suspend: block login, rewrite nginx, lock SFTP, kill sessions."""
    ensure_role(current_user.role, Role.reseller)
    user = managed_user(db, current_user, user_id)
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot suspend yourself")

    user.is_active = False
    user.token_version = (user.token_version or 0) + 1

    websites = db.query(Website).filter(Website.owner_id == user.id).all()
    for website in websites:
        website.status = "suspended"
        nginx.delete_wordpress_vhost(website.domain)
        nginx.write_suspended_vhost(website.domain, website.root_path, php_version=website.php_version,
                                    document_root=website.document_root or "public_html")
        if website.linux_user:
            try:
                site_users.lock_linux_user(website.linux_user)
            except Exception:
                pass

    # Sub-accounts share the site user's uid but not its name, so locking the
    # site user above does not touch them. A suspended customer with a working
    # SFTP sub-account still has write access to the sites just disabled.
    teardown.set_owner_sftp_accounts_locked(db, user.id, True)

    db.commit()
    log_action(db, current_user.id, "suspend_user", user.username, request=request)
    return {"message": f"Suspended user {user.username}", "affected_websites": len(websites)}

@router.post("/{user_id}/unsuspend")
def unsuspend_user(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Full unsuspend: restore login, nginx config, unlock SFTP."""
    ensure_role(current_user.role, Role.reseller)
    user = managed_user(db, current_user, user_id)

    user.is_active = True

    websites = db.query(Website).filter(Website.owner_id == user.id).all()
    for website in websites:
        website.status = "active"
        rewrite_mode = "front_controller" if website.app_type == "wordpress" else (website.nginx_rewrite_mode or "none")
        php_socket = site_users.site_php_fpm_socket(website.linux_user, website.root_path, website.php_version) if website.app_type in {"wordpress", "php"} else None
        nginx.rewrite_vhost(
            website.domain,
            website.root_path,
            app_type=website.app_type,
            php_version=website.php_version,
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

    teardown.set_owner_sftp_accounts_locked(db, user.id, False)

    db.commit()
    log_action(db, current_user.id, "unsuspend_user", user.username, request=request)
    return {"message": f"Unsuspended user {user.username}", "affected_websites": len(websites)}


@router.get("/audit/log", response_model=List[AuditLogOut])
def list_audit(
    request: Request,
    user_id: Optional[int] = Query(default=None),
    action: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_role(current_user.role, Role.admin)
    query = db.query(AuditLog).order_by(AuditLog.id.desc())
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    rows = query.offset(offset).limit(limit).all()
    entries = [AuditLogOut.from_row(row) for row in rows]
    if demo_mode.is_demo_session(current_user, getattr(request.state, "jwt_payload", None)):
        # Every visitor is the same demo account; none of them should see where
        # the others came from.
        for entry in entries:
            entry.detail = demo_mode.mask_ips(entry.detail)
            entry.target = demo_mode.mask_ips(entry.target)
    return entries
