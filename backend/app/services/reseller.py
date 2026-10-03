"""A reseller's share of the server, and what it has handed out of it.

The pool is set by the admin (users.pool_*, 0 = unlimited). Out of it come the
reseller's own account limits and every customer's: the sum of each resource
across those accounts may not exceed the pool. The per-account limits are
therefore still what websites, disk, mailboxes and applications are checked
against day to day; the pool only bounds what the reseller can hand out.

In BPanel an account's 0 means none - no websites, no bytes, no mailboxes, no
applications - so every account limit simply adds up. Applications come from
the account's package (node_apps_limit), as everywhere else in the panel.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import User, UserPackage

# (account limit, pool limit, label)
RESOURCES = (
    ("website_limit", "pool_website_limit", "websites"),
    ("storage_limit_mb", "pool_storage_limit_mb", "MB of storage"),
    ("mail_accounts_limit", "pool_mail_accounts_limit", "mailboxes"),
    ("app_limit", "pool_app_limit", "applications"),
)
POOL_FIELDS = ("pool_user_limit",) + tuple(pool for _, pool, _ in RESOURCES)
ACCOUNT_FIELDS = ("website_limit", "storage_limit_mb", "mail_accounts_limit")


def customers(db: Session, reseller: User) -> list[User]:
    if reseller.id is None:
        # Not saved yet: no customers - and `reseller_id == None` would match
        # every account the admin owns.
        return []
    return db.query(User).filter(User.reseller_id == reseller.id).order_by(User.id).all()


def account_limits(account: User, changes: Optional[dict] = None) -> dict:
    """An account's limits, with ``changes`` applied. ``changes`` may carry a
    ``package`` (or None) for the applications limit."""
    changes = changes or {}
    values = {field: int(getattr(account, field) or 0) for field in ACCOUNT_FIELDS}
    for field in ACCOUNT_FIELDS:
        if changes.get(field) is not None:
            values[field] = int(changes[field])
    package = changes["package"] if "package" in changes else getattr(account, "package", None)
    values["app_limit"] = int(getattr(package, "node_apps_limit", 0) or 0)
    return values


def check_pool(db: Session, reseller: User, *, pool: Optional[dict] = None,
               changes: Optional[dict[int, dict]] = None, new_account: Optional[dict] = None,
               leaving: Optional[set[int]] = None) -> None:
    """Raise ValueError if the reseller's accounts would not fit its pool.

    ``pool`` overrides the stored pool (an admin editing it), ``changes`` maps
    account id -> limits being set, ``new_account`` is the limits of a customer
    about to be created (as account_limits returns them), ``leaving`` the ids
    of customers about to go.
    """
    pools = {field: int(getattr(reseller, field) or 0) for field in POOL_FIELDS}
    for field, value in (pool or {}).items():
        if field in pools and value is not None:
            pools[field] = int(value)
    changes = changes or {}
    leaving = leaving or set()

    accounts = [account_limits(reseller, changes.get(reseller.id))]
    members = [c for c in customers(db, reseller) if c.id not in leaving]
    accounts += [account_limits(c, changes.get(c.id)) for c in members]
    customer_count = len(members)
    if new_account is not None:
        accounts.append(new_account)
        customer_count += 1

    if pools["pool_user_limit"] and customer_count > pools["pool_user_limit"]:
        raise ValueError(
            f"This reseller may have {pools['pool_user_limit']} customers; this would make {customer_count}."
        )
    for field, pool_field, label in RESOURCES:
        limit = pools[pool_field]
        if not limit:
            continue
        total = sum(int(account.get(field) or 0) for account in accounts)
        if total > limit:
            raise ValueError(f"The reseller's accounts would hold {total} {label}; its share is {limit}.")


def check_package_grants(reseller: User, package: Optional[UserPackage]) -> None:
    """A reseller cannot hand out a terminal it does not have itself."""
    if package is not None and package.terminal_enabled and not reseller.terminal_enabled:
        raise ValueError("Your account has no terminal, so your packages cannot include one")


def usage(db: Session, reseller: User) -> dict:
    """The pool and what has been handed out of it, for the panel."""
    members = customers(db, reseller)
    accounts = [account_limits(reseller)] + [account_limits(c) for c in members]
    out = {"customers": len(members), "pool_user_limit": int(reseller.pool_user_limit or 0)}
    for field, pool_field, _label in RESOURCES:
        out[pool_field] = int(getattr(reseller, pool_field) or 0)
        out[f"allocated_{field}"] = sum(account[field] for account in accounts)
    return out
