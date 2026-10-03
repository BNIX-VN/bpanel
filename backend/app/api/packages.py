from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.permissions import Role, ensure_role, is_reseller_role
from app.models.entities import User, UserPackage
from app.schemas.schemas import UserPackageCreate, UserPackageOut, UserPackageUpdate
from app.services import reseller as reseller_pool
from app.services.audit import log_action

router = APIRouter(prefix="/packages", tags=["packages"])


def _owner(user: User):
    """Whose packages this caller manages: a reseller's own, or the admin's (None)."""
    ensure_role(user.role, Role.reseller)
    return user.id if is_reseller_role(user.role) else None


def _scoped(db: Session, owner_id):
    # The admin's packages are the ones with no owner: they are what WHMCS and
    # the provisioning API see. A reseller's own packages never reach them.
    query = db.query(UserPackage)
    if owner_id is None:
        return query.filter(UserPackage.owner_id.is_(None))
    return query.filter(UserPackage.owner_id == owner_id)


def _package_by_id(db: Session, package_id: int, owner_id=None) -> UserPackage:
    package = _scoped(db, owner_id).filter(UserPackage.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


def _ensure_unique_name(db: Session, name: str, package_id: int | None = None, owner_id=None) -> None:
    query = _scoped(db, owner_id).filter(UserPackage.name == name)
    if package_id is not None:
        query = query.filter(UserPackage.id != package_id)
    if query.first():
        raise HTTPException(status_code=409, detail="Package name already exists")


def _check_grants(user: User, package) -> None:
    if is_reseller_role(user.role):
        try:
            reseller_pool.check_package_grants(user, package)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=List[UserPackageOut])
def list_packages(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _scoped(db, _owner(current_user)).order_by(UserPackage.id.asc()).all()


@router.post("", response_model=UserPackageOut)
def create_package(
    payload: UserPackageCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owner_id = _owner(current_user)
    _ensure_unique_name(db, payload.name, owner_id=owner_id)
    package = UserPackage(
        owner_id=owner_id,
        name=payload.name,
        slug=payload.slug,
        website_limit=payload.website_limit,
        storage_limit_mb=payload.storage_limit_mb,
        database_limit=payload.database_limit,
        alias_limit=payload.alias_limit,
        backup_retention_days=payload.backup_retention_days,
        terminal_enabled=payload.terminal_enabled,
        waf_enabled=payload.waf_enabled,
        wordpress_enabled=payload.wordpress_enabled,
        node_apps_limit=payload.node_apps_limit,
        sftp_accounts_limit=payload.sftp_accounts_limit,
        mail_accounts_limit=payload.mail_accounts_limit,
        node_app_memory_mb=payload.node_app_memory_mb,
    )
    _check_grants(current_user, package)
    db.add(package)
    db.commit()
    db.refresh(package)
    log_action(db, current_user.id, "create_package", package.name, request=request)
    return package


@router.patch("/{package_id}", response_model=UserPackageOut)
def update_package(
    package_id: int,
    payload: UserPackageUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owner_id = _owner(current_user)
    package = _package_by_id(db, package_id, owner_id)
    if payload.name is not None and payload.name != package.name:
        _ensure_unique_name(db, payload.name, package_id=package.id, owner_id=owner_id)
        package.name = payload.name
    if payload.slug is not None:
        package.slug = payload.slug
    if payload.website_limit is not None:
        package.website_limit = payload.website_limit
    if payload.storage_limit_mb is not None:
        package.storage_limit_mb = payload.storage_limit_mb
    if payload.database_limit is not None:
        package.database_limit = payload.database_limit
    if payload.alias_limit is not None:
        package.alias_limit = payload.alias_limit
    if payload.backup_retention_days is not None:
        package.backup_retention_days = payload.backup_retention_days
    if payload.terminal_enabled is not None:
        package.terminal_enabled = payload.terminal_enabled
    if payload.waf_enabled is not None:
        package.waf_enabled = payload.waf_enabled
    if payload.wordpress_enabled is not None:
        package.wordpress_enabled = payload.wordpress_enabled
    if payload.node_apps_limit is not None:
        package.node_apps_limit = payload.node_apps_limit
    if payload.sftp_accounts_limit is not None:
        package.sftp_accounts_limit = payload.sftp_accounts_limit
    if payload.mail_accounts_limit is not None:
        package.mail_accounts_limit = payload.mail_accounts_limit
    if payload.node_app_memory_mb is not None:
        package.node_app_memory_mb = payload.node_app_memory_mb
    assigned = db.query(User).filter(User.package_id == package.id).all()
    if owner_id is not None:
        # The customers on this package take its new limits: all of them must
        # still fit in the reseller's share, and nothing it cannot grant.
        try:
            reseller_pool.check_package_grants(current_user, package)
            reseller_pool.check_pool(db, current_user, changes={
                user.id: {"website_limit": package.website_limit, "storage_limit_mb": package.storage_limit_mb,
                          "database_limit": package.database_limit, "package": package}
                for user in assigned
            })
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for user in assigned:
        user.website_limit = package.website_limit
        user.storage_limit_mb = package.storage_limit_mb
        user.database_limit = package.database_limit
    db.commit()
    db.refresh(package)
    log_action(db, current_user.id, "update_package", package.name, request=request)
    return package


@router.delete("/{package_id}")
def delete_package(
    package_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    package = _package_by_id(db, package_id, _owner(current_user))
    if db.query(User).filter(User.package_id == package.id).first():
        raise HTTPException(status_code=400, detail="Package is in use")
    name = package.name
    db.delete(package)
    db.commit()
    log_action(db, current_user.id, "delete_package", name, request=request)
    return {"ok": True}
