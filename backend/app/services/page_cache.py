"""A website's Nginx page cache (FastCGI cache): on, off, emptied.

Nginx keeps the pages a WordPress website serves to visitors who are not
signed in, for 10 minutes, and never wp-admin, a logged-in visitor, a POST or
a cart (templates/nginx/wordpress.conf.j2). It is the website's: turned on and
off from its own page's Cache tab and from the WordPress Manager's, and on
until turned off (websites.nginx_cache_enabled).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Website
from app.services.shell import shell


class PageCacheError(ValueError):
    pass


def available(website: Website) -> bool:
    """Only a website in WordPress mode has the cache: its vhost carries the
    skip rules (wp-admin, sign-in cookies, WooCommerce) a cache needs."""
    return (website.app_type or "wordpress") == "wordpress"


def purge(website: Website) -> int:
    """The website's pages out of the cache; how many went."""
    result = shell.privileged("fastcgi-cache-purge", helper_args=[website.domain], check=False,
                              fallback=["bash", "-lc", "echo 0"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise PageCacheError("The cache could not be emptied: " + (detail[-1] if detail else "the helper failed"))
    numbers = [word for word in (result.stdout or "").split() if word.isdigit()]
    return int(numbers[-1]) if numbers else 0


def set_enabled(db: Session, website: Website, enabled: bool) -> None:
    """Turn the cache on or off: the website's vhost written again. Turning it
    off empties what it kept, so nothing old is served if it comes back on."""
    if not available(website):
        raise PageCacheError("The Nginx cache serves websites in WordPress mode: set this website's mode to WordPress first")
    from app.api.websites import _rewrite_website_vhost

    previous = bool(website.nginx_cache_enabled)
    website.nginx_cache_enabled = bool(enabled)
    db.commit()
    try:
        _rewrite_website_vhost(website)
    except Exception:
        website.nginx_cache_enabled = previous
        db.commit()
        raise
    if not enabled:
        purge(website)
