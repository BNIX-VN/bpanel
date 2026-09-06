"""The web server this install drives - "nginx" or "openlitespeed", chosen at
install time (WEB_SERVER in .env, see app.core.config.Settings.web_server).

Anything that renders a vhost, toggles WAF, reads a site log, syncs HTTP-flood
zones, and so on goes through here instead of importing `nginx` (or, once it
exists, `openlitespeed`) directly. Today there is exactly one backend -
`nginx.py` - and this module is a transparent, zero-behaviour-change
indirection in front of it; the point is that the ~30 call sites across the
codebase stop hardcoding "nginx" so a second backend can be dropped in later
without touching them again.

Both backends are expected to expose the same interface: `render_vhost`,
`rewrite_vhost`, `write_vhost`, `delete_wordpress_vhost`, `read_vhost_config`,
`read_site_log`, `clear_site_log`, `update_waf_block`,
`update_http_flood_block`, `update_custom_block`, `sync_http_flood_zones`,
`validate_http_flood_config`, `http_flood_config_for_website`, `vhost_exists`,
plus the constants `PROXIED_APP_TYPES` / `ALLOWED_APP_TYPES` /
`ALLOWED_REWRITE_MODES` / `ALLOWED_PHP_VERSIONS`. `nginx.py` is the reference
implementation of that interface.
"""

import importlib

from app.core.config import settings

# Anything else (a stray value in an old .env, a typo) falls back to nginx
# rather than raising - a website should never fail to render because this
# setting came out wrong.
_ALIASES = {
    "nginx": "nginx",
    "openlitespeed": "openlitespeed",
    "ols": "openlitespeed",
    "litespeed": "openlitespeed",
}


def active_name() -> str:
    """The backend module name this install should use: "nginx" or "openlitespeed"."""
    return _ALIASES.get((settings.web_server or "nginx").strip().lower(), "nginx")


def backend():
    """The active backend module itself (`app.services.nginx` today)."""
    return importlib.import_module(f"app.services.{active_name()}")


def __getattr__(name):
    # PEP 562: makes `webserver.rewrite_vhost(...)` and `webserver.PROXIED_APP_TYPES`
    # both resolve to the active backend's attribute, for functions and
    # constants alike - callers never need to know which backend is live.
    return getattr(backend(), name)
