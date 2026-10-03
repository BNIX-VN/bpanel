"""A reseller's share of the server: how many customers, and how much disk.

The share is set by the admin (users.pool_user_limit and
users.pool_storage_limit_mb, 0 = unlimited). It holds the number of
customers and disk, and nothing else (operator, 2026-10-03): websites,
databases, mailboxes and applications are the reseller's to give its
customers as it sees fit, through their own account limits.

Disk is counted in one of two ways, the admin's choice per reseller:

- by what is handed out (the default): the reseller's own disk limit plus
  every customer's may not exceed the share. In BPanel an account's disk
  limit of 0 means none, so the limits simply add up.
- by what is used (users.pool_oversell), as cPanel and DirectAdmin
  oversell: the limits handed out are not added up, and what the reseller's
  accounts actually hold on disk is checked against the share whenever one
  of them writes more (ensure_storage_room, from enforce_user_storage_quota).

Customers are counted the same way either way.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import User, UserPackage

POOL_FIELDS = ("pool_user_limit", "pool_storage_limit_mb")
OVERSELL = "pool_oversell"
# Every share setting, and what an account that is not a reseller holds.
SETTINGS = POOL_FIELDS + (OVERSELL,)
NO_POOL = {**{field: 0 for field in POOL_FIELDS}, OVERSELL: False}
# The account limits a share bounds.
ACCOUNT_FIELDS = ("storage_limit_mb",)


def customers(db: Session, reseller: User) -> list[User]:
    if reseller.id is None:
        # Not saved yet: no customers - and `reseller_id == None` would match
        # every account the admin owns.
        return []
    return db.query(User).filter(User.reseller_id == reseller.id).order_by(User.id).all()


def account_limits(account: User, changes: Optional[dict] = None) -> dict:
    """An account's limits that count against a share, with ``changes`` applied.
    Anything else in ``changes`` (other limits, a ``package``) is ignored."""
    value = (changes or {}).get("storage_limit_mb")
    return {"storage_limit_mb": int(value if value is not None else (getattr(account, "storage_limit_mb", 0) or 0))}


def check_pool(db: Session, reseller: User, *, pool: Optional[dict] = None,
               changes: Optional[dict[int, dict]] = None, new_account: Optional[dict] = None,
               leaving: Optional[set[int]] = None) -> None:
    """Raise ValueError if the reseller's accounts would not fit its share.

    ``pool`` overrides the stored share (an admin editing it), ``changes`` maps
    account id -> limits being set, ``new_account`` is the limits of a customer
    about to be created (as account_limits returns them), ``leaving`` the ids
    of customers about to go.
    """
    pools = {field: int(getattr(reseller, field) or 0) for field in POOL_FIELDS}
    for field, value in (pool or {}).items():
        if field in pools and value is not None:
            pools[field] = int(value)
    oversell = bool(getattr(reseller, OVERSELL, False))
    if (pool or {}).get(OVERSELL) is not None:
        oversell = bool(pool[OVERSELL])
    changes = changes or {}
    leaving = leaving or set()

    disks = [account_limits(reseller, changes.get(reseller.id))["storage_limit_mb"]]
    members = [c for c in customers(db, reseller) if c.id not in leaving]
    disks += [account_limits(c, changes.get(c.id))["storage_limit_mb"] for c in members]
    customer_count = len(members)
    if new_account is not None:
        disks.append(int(new_account.get("storage_limit_mb") or 0))
        customer_count += 1

    if pools["pool_user_limit"] and customer_count > pools["pool_user_limit"]:
        raise ValueError(
            f"This reseller may have {pools['pool_user_limit']} customers; this would make {customer_count}."
        )
    limit = pools["pool_storage_limit_mb"]
    if oversell or not limit:
        # Overselling: what the accounts hold is checked when they write it.
        return
    if sum(disks) > limit:
        raise ValueError(f"The reseller's accounts would hold {sum(disks)} MB of disk; its share is {limit} MB.")


def check_package_grants(reseller: User, package: Optional[UserPackage]) -> None:
    """A reseller cannot hand out a terminal it does not have itself."""
    if package is not None and package.terminal_enabled and not reseller.terminal_enabled:
        raise ValueError("Your account has no terminal, so your packages cannot include one")


def usage(db: Session, reseller: User) -> dict:
    """The share, what has been handed out of it and what is in use, for the panel."""
    members = customers(db, reseller)
    accounts = [reseller] + members
    return {
        "customers": len(members),
        "pool_user_limit": int(reseller.pool_user_limit or 0),
        "pool_storage_limit_mb": int(reseller.pool_storage_limit_mb or 0),
        OVERSELL: bool(getattr(reseller, OVERSELL, False)),
        "allocated_storage_limit_mb": sum(int(account.storage_limit_mb or 0) for account in accounts),
        "used_storage_limit_mb": _storage_used_bytes(db, accounts) // (1024 * 1024),
    }


# --- overselling: what the accounts actually hold on disk --------------------------------

def reseller_of(db: Session, account: User) -> Optional[User]:
    """The reseller whose share this account's disk comes out of."""
    from app.core.permissions import is_reseller_role

    if is_reseller_role(account.role):
        return account
    if not account.reseller_id:
        return None
    owner = db.query(User).filter(User.id == account.reseller_id).first()
    return owner if owner is not None and is_reseller_role(owner.role) else None


def _storage_used_bytes(db: Session, accounts: list[User], fresh: Optional[User] = None) -> int:
    from app.services import storage_quota

    return sum(storage_quota.user_storage_used_bytes(db, account, use_cache=fresh is None or account.id != fresh.id)
               for account in accounts)


def ensure_storage_room(db: Session, account: User, *, incoming_bytes: int = 0, replaced_bytes: int = 0) -> None:
    """Refuse a write that would take an overselling reseller's accounts past
    its disk share. The account writing is measured afresh; the others come
    from the usage cache, which is minutes old at most."""
    reseller = reseller_of(db, account)
    if reseller is None or not getattr(reseller, OVERSELL, False):
        return
    limit_mb = int(reseller.pool_storage_limit_mb or 0)
    if not limit_mb or max(0, incoming_bytes) <= max(0, replaced_bytes):
        return
    accounts = [reseller] + customers(db, reseller)
    used = _storage_used_bytes(db, accounts, fresh=account)
    projected = max(0, used - max(0, replaced_bytes)) + max(0, incoming_bytes)
    if projected > limit_mb * 1024 * 1024:
        raise ValueError(
            f"The reseller's share of disk is used up: {projected // (1024 * 1024)} MB used/projected, "
            f"share {limit_mb} MB."
        )
