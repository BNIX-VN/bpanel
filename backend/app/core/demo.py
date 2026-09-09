"""Demo mode: the panel becomes a place to look, not a place to act.

Turning this on is a decision about a whole server, so it is made outside the
panel - DEMO_MODE in backend/.env - and there is deliberately no API that can
change it. A demo is normally handed out with working admin credentials; if the
switch were reachable from inside, the first visitor could turn it off and then
do anything at all.

What a demo visitor may do is everything that only reads: every dashboard,
list and detail page, service and firewall status, WAF rules, logs. That is
what someone evaluating a control panel actually wants to see.

What they may not do falls into three groups, and the second and third are the
ones that make a "read-only" demo built on HTTP verbs alone insufficient:

  1. Anything that changes state. Every POST/PUT/PATCH/DELETE, with a narrow
     allowance for the login flow itself.
  2. GETs that hand data out - file, database and backup downloads. They are
     reads by HTTP method and exfiltration by effect, and they are a bandwidth
     bill on a public server.
  3. GETs that are doors out of the panel. The phpMyAdmin SSO route consumes a
     token and lands the visitor in phpMyAdmin with real database access;
     nothing after that point is the panel's to control.

The terminal is refused wherever it appears. Its exec route is a POST and so
already covered, but the websocket never passes through HTTP middleware and
has to check for itself.
"""

from app.core.config import settings

# The login flow has to keep working, or the demo cannot be entered at all.
ALLOWED_MUTATIONS = frozenset(
    {
        "/api/auth/login",
        "/api/auth/logout",
    }
)

# Reads that are not really reads.
BLOCKED_READ_PREFIXES = (
    "/api/terminal",
    "/api/databases/phpmyadmin-sso",
)

BLOCKED_READ_MARKERS = (
    # Bare, because the routes are not consistent about the separator:
    # /databases/{id}/download but /maintenance/user-backups-download. No
    # read-only route has "download" in its path for any other reason.
    "download",
    # This one keeps its slash: bare "read" would also match "thread",
    # "already" and anything else that happens to contain it.
    "/read",
)

MESSAGE = "This panel is running in demo mode. Everything is visible, nothing can be changed."


def enabled() -> bool:
    return bool(getattr(settings, "demo_mode", False))


def blocks(method: str, path: str) -> bool:
    """Whether demo mode refuses this request.

    Pure and side-effect free so it can be unit tested against the real route
    table rather than by reasoning about middleware.
    """
    if not enabled():
        return False

    normalized = path.rstrip("/") or "/"

    if any(normalized.startswith(prefix) for prefix in BLOCKED_READ_PREFIXES):
        return True

    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        # user-backups-download and friends carry the marker in the last
        # segment; files/{id}/read and app-files/{id}/read end with it.
        return any(marker in normalized for marker in BLOCKED_READ_MARKERS)

    return normalized not in ALLOWED_MUTATIONS
