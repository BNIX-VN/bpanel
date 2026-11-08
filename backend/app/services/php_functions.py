"""The PHP functions a website's PHP may not call (operator, 2026-11-08).

Every site's PHP-FPM pool disables DEFAULT_DISABLED unless the site has a list
of its own: a customer who needs one of them takes it off on the website's PHP
tab and saves. The pool carries it as php_admin_value[disable_functions], so
the site's own code - ini_set(), a .user.ini - cannot take it back.

The helper keeps each site's list in a root-owned marker keyed by the site's
path (bpanel-helper.sh, PHP_DISABLE_ROOT), so every rewrite of the pool keeps
it; Website.disable_functions mirrors it for the panel: None is the default
list, "" is nothing disabled. The helper holds the same default list.
"""
from __future__ import annotations

import re
from typing import Optional

from app.models.entities import Website
from app.services import site_users

DEFAULT_DISABLED = (
    "exec", "system", "passthru", "shell_exec", "proc_close", "proc_open", "dl", "show_source",
    "posix_kill", "posix_mkfifo", "posix_getpwuid", "posix_setpgid", "posix_setsid", "posix_setuid",
    "posix_setgid", "posix_seteuid", "posix_setegid", "posix_uname",
)
NAME_RE = re.compile(r"[a-z_][a-z0-9_]{0,63}")
MAX_NAMES = 200


def normalize(text: Optional[str]) -> Optional[str]:
    """A comma list of function names, in the order given, each once; None
    stays None (the default list)."""
    if text is None:
        return None
    names: list[str] = []
    for raw in re.split(r"[\s,]+", text.strip().lower()):
        if not raw:
            continue
        if not NAME_RE.fullmatch(raw):
            raise ValueError(f"Not a PHP function name: {raw}")
        if raw not in names:
            names.append(raw)
    if len(names) > MAX_NAMES:
        raise ValueError(f"At most {MAX_NAMES} functions")
    return ",".join(names)


def effective(website: Website) -> list[str]:
    value = getattr(website, "disable_functions", None)
    if value is None:
        return list(DEFAULT_DISABLED)
    return [name for name in value.split(",") if name]


def runtime_php_version(website: Website) -> Optional[str]:
    return website.php_version if (website.app_type or "wordpress") in {"wordpress", "php"} else None


def apply(website: Website, functions: Optional[str]) -> None:
    """Write the site's list into its pool and onto the row. None goes back to
    the default list. The row changes only once the pool has."""
    value = normalize(functions)
    if website.linux_user:
        if value is None:
            helper_value = "default"
        else:
            helper_value = value or "none"
        site_users.set_php_disable(website.root_path, runtime_php_version(website), website.linux_user, helper_value)
    website.disable_functions = value
