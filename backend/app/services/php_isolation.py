"""open_basedir for a site's PHP-FPM pool: off unless the site, or its package, asks.

open_basedir makes PHP resolve and check every path it opens: on .88 that cost
a third of every uncached WordPress page (0.22 s -> 0.15 s, 14 -> 22 req/s,
2026-10-23). Customers do not depend on it to stay apart - each one's PHP runs
as its own user and /home/<user> is 0750 - so it fences one customer's own
sites from each other, and it is the host's choice: off by default, on for
every site of a package that has it on, and settable per site by whoever
manages the account (operator, 2026-10-22, as OPanel).

The helper keeps the state in a root-owned marker per site
(bpanel-helper.sh, PHP_BASEDIR_ROOT), so every rewrite of the pool - a PHP
version change, the update, a cron job - keeps it without being told.

Turning it on or off for a package moves every site of every account on that
package with it; putting an account on a package moves that account's sites to
the package's value.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import User, UserPackage, Website
from app.services import site_users


def package_of(db: Session, user: User | None) -> UserPackage | None:
    package_id = getattr(user, "package_id", None) if user is not None else None
    if not package_id:
        return None
    return db.query(UserPackage).filter(UserPackage.id == package_id).first()


def default_for(db: Session, owner: User | None) -> bool:
    """What a new site of this owner starts with: its package's value, else off."""
    package = package_of(db, owner)
    return bool(package and package.open_basedir)


def runtime_php_version(website: Website) -> str | None:
    return website.php_version if (website.app_type or "wordpress") in {"wordpress", "php"} else None


def apply(db: Session, websites: list[Website], on: bool) -> list[str]:
    """Set the flag on these sites and rewrite each pool whose value moved.

    Returns the domains whose pool could not be rewritten; their flag is left
    as it was, so the database never claims what the pool does not do.
    """
    failed: list[str] = []
    for website in websites:
        if bool(website.open_basedir) == bool(on):
            continue
        if website.linux_user:
            try:
                site_users.set_php_basedir(website.root_path, runtime_php_version(website), website.linux_user, bool(on))
            except (RuntimeError, ValueError, OSError):
                failed.append(website.domain)
                continue
        website.open_basedir = bool(on)
    db.commit()
    return failed


def sync_user(db: Session, user: User) -> list[str]:
    """Bring an account's sites to its package's value (after a package change)."""
    package = package_of(db, user)
    if package is None:
        return []
    sites = db.query(Website).filter(Website.owner_id == user.id).all()
    return apply(db, sites, bool(package.open_basedir))


def sync_package(db: Session, package: UserPackage) -> list[str]:
    """Every site of every account on this package, to the package's value."""
    owner_ids = [row[0] for row in db.query(User.id).filter(User.package_id == package.id).all()]
    if not owner_ids:
        return []
    sites = db.query(Website).filter(Website.owner_id.in_(owner_ids)).all()
    return apply(db, sites, bool(package.open_basedir))
