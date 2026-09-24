"""The tools an assistant can actually call.

Separate from `mcp.py` on purpose: that file is the transport and the
permission model, this one is the surface area. They change for different
reasons and at different rates, and a reviewer reading one should not have to
scroll past the other.

Every tool here calls the API's own endpoint function rather than reaching
into a service or the database. That is the single most important rule in the
file. Ownership checks, quota, audit and the sudo helper boundary all live
inside those endpoints; a tool that went around them would be a second
implementation of the panel's permission model, and the two would drift.

Websites are addressed by domain, because that is what a person says to an
assistant and what the assistant reads in a log. Somebody else's domain is
reported as not existing - never as forbidden, which would confirm it is real.

Importing this module is what registers the tools. `app.api.mcp` imports it
for that reason and uses nothing from it.
"""

from __future__ import annotations

from typing import Optional

from app.api import databases as databases_api
from app.api import firewall as firewall_api
from app.api import maintenance as maintenance_api
from app.api import services as services_api
from app.api import updates as updates_api
from app.api import users as users_api
from app.api import waf as waf_api
from app.api import websites as websites_api
from app.core.permissions import is_admin_role
from app.models.entities import User, Website
from app.services import file_manager
from app.services import waf as waf_service
from app.services.mcp import DOMAIN_ARG, Context, ToolError, tool


# --- shared lookups ---------------------------------------------------------

def _website(ctx: Context, domain: str) -> Website:
    """The website this domain names, if the caller may see it.

    A domain belonging to another account raises the same error as one that
    was never created. Saying "not yours" would tell a customer's assistant
    which domains exist on the server.
    """
    wanted = (domain or "").strip().lower().lstrip(".")
    if not wanted:
        raise ToolError("A domain is required")
    query = ctx.db.query(Website).filter(Website.domain == wanted)
    if not is_admin_role(ctx.user.role):
        query = query.filter(Website.owner_id == ctx.user.id)
    website = query.first()
    if website is None:
        raise ToolError(
            f"No website named {wanted}. Use list_websites to see what there is."
        )
    return website


def _rows(value) -> list:
    """Endpoints return models, dicts or a wrapper; tools return plain data."""
    if isinstance(value, dict):
        for key in ("items", "rows", "results"):
            if key in value and isinstance(value[key], list):
                return value[key]
        return [value]
    if isinstance(value, list):
        return value
    return [value]


def _thin(row, *fields) -> dict:
    """Only the fields an assistant can use.

    Everything sent here is tokens the model pays for and context it has to
    read past. Password hashes and internal ids are also simply not its
    business.
    """
    out = {}
    for name in fields:
        value = getattr(row, name, None) if not isinstance(row, dict) else row.get(name)
        if value is not None:
            out[name] = value
    return out


# --- who am I ---------------------------------------------------------------

@tool("whoami", "Who this token belongs to",
      "The account this token acts as, and what it may do. Call this first if "
      "you are unsure whether you are working as an administrator or as one "
      "hosting customer - it decides which other tools exist.")
def _whoami(ctx: Context, args: dict):
    return {
        "username": ctx.user.username,
        "role": "administrator" if ctx.is_admin else "hosting customer",
        "can_make_changes": ctx.can_write,
        "token_name": ctx.token.name,
        "token_expires_at": ctx.token.expires_at,
        "scope": "every website on this server" if ctx.is_admin
                 else "only websites owned by this account",
    }


# --- websites ---------------------------------------------------------------

@tool("list_websites", "List websites",
      "Every website you can see, with its domain, PHP version and whether "
      "SSL and the firewall rules are on. Start here: the other tools take a "
      "domain, and this is where the domains come from.",
      {"search": {"type": "string", "maxLength": 255,
                  "description": "Optional. Matches domain, path or Linux user."}})
def _list_websites(ctx: Context, args: dict):
    found = websites_api.list_websites(
        q=args.get("search", ""), db=ctx.db, current_user=ctx.user)
    return {"websites": [
        _thin(row, "domain", "php_version", "app_type", "status",
              "ssl_enabled", "waf_enabled", "root_path")
        for row in _rows(found)
    ]}


@tool("read_site_log", "Read a website's log",
      "The tail of one website's access or error log. Use the error log when "
      "a site is failing and the access log when you need to see what traffic "
      "it is getting.",
      {"domain": DOMAIN_ARG,
       "kind": {"type": "string", "enum": ["access", "error"],
                "description": "Which log. Defaults to access."},
       "lines": {"type": "integer", "minimum": 1, "maximum": 5000,
                 "description": "How many lines from the end. Defaults to 200."}},
      required=("domain",))
def _read_site_log(ctx: Context, args: dict):
    website = _website(ctx, args["domain"])
    return websites_api.get_website_log(
        website_id=website.id, kind=args.get("kind", "access"),
        lines=args.get("lines", 200), db=ctx.db, current_user=ctx.user)


# --- databases --------------------------------------------------------------

@tool("list_databases", "List databases",
      "The MySQL databases you can see, and which website each belongs to. "
      "Passwords are never included.",
      {"search": {"type": "string", "maxLength": 255}})
def _list_databases(ctx: Context, args: dict):
    found = databases_api.list_databases(
        q=args.get("search", ""), db=ctx.db, current_user=ctx.user)
    return {"databases": [
        _thin(row, "db_name", "db_user", "website_id", "size_mb", "created_at")
        for row in _rows(found)
    ]}


# --- backups ----------------------------------------------------------------

@tool("list_backups", "List an account's backups",
      "The backup archives held for an account, newest first. Administrators "
      "may name any account; everyone else gets their own.",
      {"username": {"type": "string", "maxLength": 64,
                    "description": "Administrators only. Defaults to your own account."}})
def _list_backups(ctx: Context, args: dict):
    owner = ctx.user
    wanted = (args.get("username") or "").strip()
    if wanted and wanted != ctx.user.username:
        if not ctx.is_admin:
            raise ToolError(f"No account named {wanted}")
        owner = ctx.db.query(User).filter(User.username == wanted).first()
        if owner is None:
            raise ToolError(f"No account named {wanted}")
    return maintenance_api.list_user_backups(
        user_id=owner.id, db=ctx.db, current_user=ctx.user)


@tool("list_backup_jobs", "List running and recent backup jobs",
      "Backup jobs and their state. Use this after starting a backup to see "
      "whether it finished, rather than assuming it did.")
def _list_backup_jobs(ctx: Context, args: dict):
    return maintenance_api.list_backup_jobs(current_user=ctx.user)


@tool("list_backup_schedules", "List scheduled backups",
      "Every backup schedule on the server: when it runs, where it sends the "
      "archive, how many it keeps, and how the last run went. The last "
      "message is where a failing schedule says why.",
      admin_only=True)
def _list_backup_schedules(ctx: Context, args: dict):
    found = maintenance_api.list_backup_schedules(db=ctx.db, current_user=ctx.user)
    return {"schedules": [
        _thin(row, "id", "schedule", "retention", "name_suffix", "is_active",
              "last_run_at", "last_status", "last_message")
        for row in _rows(found)
    ]}


# --- the server -------------------------------------------------------------

@tool("server_resources", "CPU, memory and disk",
      "What the machine is doing right now. Use this before blaming a site "
      "for being slow - the answer is often that the box is out of memory.")
def _server_resources(ctx: Context, args: dict):
    return services_api.get_resource_usage(current_user=ctx.user)


@tool("list_services", "List system services",
      "nginx, PHP-FPM, MariaDB, Redis and the rest, with whether each is "
      "running. Check here before restarting anything.",
      admin_only=True)
def _list_services(ctx: Context, args: dict):
    return services_api.get_services(current_user=ctx.user)


@tool("panel_update_status", "Panel and OS update status",
      "Which version the panel is on, whether a newer release exists, and how "
      "many operating system updates are waiting.",
      admin_only=True)
def _panel_update_status(ctx: Context, args: dict):
    return updates_api.get_update_status(refresh=False, current_user=ctx.user)


# --- users and audit --------------------------------------------------------

@tool("list_users", "List panel accounts",
      "Every hosting account on the server, with its limits and whether it is "
      "suspended.",
      admin_only=True)
def _list_users(ctx: Context, args: dict):
    found = users_api.list_users(db=ctx.db, current_user=ctx.user)
    return {"users": [
        _thin(row, "id", "username", "email", "role", "is_active",
              "website_limit", "storage_limit_mb")
        for row in _rows(found)
    ]}


@tool("recent_audit_log", "Recent panel activity",
      "What has been done on this panel lately, newest first - who did it, to "
      "what, and when. Anything an assistant did appears here as mcp_tool.",
      {"limit": {"type": "integer", "minimum": 1, "maximum": 200,
                 "description": "How many entries. Defaults to 50."},
       "action": {"type": "string", "maxLength": 64,
                  "description": "Optional. Only entries with this action."}},
      admin_only=True)
def _recent_audit_log(ctx: Context, args: dict):
    return users_api.list_audit(
        user_id=None, action=args.get("action"), limit=args.get("limit", 50),
        offset=0, db=ctx.db, current_user=ctx.user)


# --- firewall and WAF -------------------------------------------------------

@tool("list_firewall_rules", "List firewall rules",
      "Whether the firewall is on and every rule it holds, with the rule "
      "numbers. A blocked address is removed by its number, so read this "
      "before unblocking anything.",
      admin_only=True)
def _list_firewall_rules(ctx: Context, args: dict):
    return firewall_api.get_status(current_user=ctx.user)


@tool("list_waf_rules", "List WAF rules",
      "The web application firewall rules available on this server, with the "
      "id of each. Use it to see what a rule id in a blocked request means.",
      admin_only=True)
def _list_waf_rules(ctx: Context, args: dict):
    return waf_api.get_waf_rules(current_user=ctx.user)


@tool("read_waf_access_log", "Read what the WAF allowed and blocked",
      "Requests the web application firewall saw, newest first, with the rule "
      "that blocked each one. This is the tool for 'why is this visitor "
      "getting a 403' and for finding an address worth blocking.",
      {"domain": {**DOMAIN_ARG, "description":
                  "Optional. Only this website's requests."},
       "verdict": {"type": "string", "enum": ["all", "allow", "block", "error"],
                   "description": "Defaults to all."},
       "search": {"type": "string", "maxLength": 200,
                  "description": "Optional. Matches the address, path or user agent."},
       "limit": {"type": "integer", "minimum": 1, "maximum": 500,
                 "description": "How many entries. Defaults to 50."}})
def _read_waf_access_log(ctx: Context, args: dict):
    website_id: Optional[int] = None
    if args.get("domain"):
        website_id = _website(ctx, args["domain"]).id
    return waf_api.get_waf_access_logs(
        website_id=website_id, verdict=args.get("verdict", "all"),
        q=args.get("search", ""), limit=args.get("limit", 50), lines=5000,
        db=ctx.db, current_user=ctx.user)


# --- files ------------------------------------------------------------------

# A model asked for "the file" will happily pull a 40 MB log into its own
# context and then be unable to do anything else. The panel's own endpoint has
# no such limit because a browser scrolling a file is a different problem.
MAX_READ_LINES = 2000


@tool("list_files", "List files in a website",
      "What is in a directory of a website, with sizes and modification "
      "times. Paths are relative to the website's root.",
      {"domain": DOMAIN_ARG,
       "path": {"type": "string", "maxLength": 1024,
                "description": "Directory relative to the website root. "
                               "Empty or omitted means the root itself."}},
      required=("domain",))
def _list_files(ctx: Context, args: dict):
    website = _website(ctx, args["domain"])
    return maintenance_api.list_files(
        website_id=website.id, path=args.get("path", ""),
        db=ctx.db, current_user=ctx.user)


@tool("read_file", "Read a file from a website",
      f"The contents of one file, up to {MAX_READ_LINES} lines. Longer files "
      "come back truncated and say so, so check that before concluding "
      "something is missing from the end.",
      {"domain": DOMAIN_ARG,
       "path": {"type": "string", "maxLength": 1024,
                "description": "File relative to the website root."}},
      required=("domain", "path"))
def _read_file(ctx: Context, args: dict):
    website = _website(ctx, args["domain"])
    result = maintenance_api.read_file(
        website_id=website.id, path=args["path"], db=ctx.db, current_user=ctx.user)

    content = result.get("content", "") if isinstance(result, dict) else str(result)
    lines = content.splitlines()
    if len(lines) <= MAX_READ_LINES:
        return {"path": args["path"], "lines": len(lines), "truncated": False,
                "content": content}
    return {
        "path": args["path"],
        "lines": MAX_READ_LINES,
        "total_lines": len(lines),
        "truncated": True,
        "note": f"Showing the first {MAX_READ_LINES} of {len(lines)} lines.",
        "content": "\n".join(lines[:MAX_READ_LINES]),
    }


# --- the three that needed something BPanel did not have --------------------

@tool("get_website", "Everything about one website",
      "One website in full: PHP version, document root, SSL state and expiry, "
      "the firewall settings and every alias pointing at it. Use this when "
      "list_websites has told you the domain and you need the detail.",
      {"domain": DOMAIN_ARG},
      required=("domain",))
def _get_website(ctx: Context, args: dict):
    """Composed rather than fetched.

    BPanel has no GET /websites/{id}: the panel builds this page from the
    listing plus two more calls, and so does this. Composing here rather than
    adding an endpoint keeps MCP from being the reason a new surface exists.
    """
    website = _website(ctx, args["domain"])
    detail = _thin(
        website, "domain", "php_version", "app_type", "status", "root_path",
        "document_root", "ssl_enabled", "waf_enabled", "waf_default_rules",
        "http_flood_enabled", "nginx_rewrite_mode", "linux_user", "created_at",
    )
    try:
        aliases = websites_api.list_website_aliases(
            website_id=website.id, db=ctx.db, current_user=ctx.user)
        detail["aliases"] = [_thin(row, "domain", "mode") for row in _rows(aliases)]
    except Exception:  # noqa: BLE001 - detail is better without it than absent
        detail["aliases"] = []
    try:
        detail["ssl"] = websites_api.ssl_sources(
            website_id=website.id, db=ctx.db, current_user=ctx.user)
    except Exception:  # noqa: BLE001
        pass
    return detail


@tool("traffic_summary", "Summarise a website's traffic",
      "What the traffic to one website looks like: how many requests, which "
      "addresses and paths account for most of them, which countries, and "
      "which addresses are being blocked. This is the tool for 'is this site "
      "under attack' and for finding an address worth blocking - it counts, "
      "so you do not have to read thousands of log lines to do arithmetic.",
      {"domain": DOMAIN_ARG,
       "lines": {"type": "integer", "minimum": 100, "maximum": 5000,
                 "description": "How far back to read. Defaults to 5000 lines."},
       "top": {"type": "integer", "minimum": 1, "maximum": 50,
               "description": "How many entries in each top list. Defaults to 10."}},
      required=("domain",))
def _traffic_summary(ctx: Context, args: dict):
    website = _website(ctx, args["domain"])
    return waf_service.access_summary(
        [website], lines=args.get("lines", 5000), top=args.get("top", 10))


@tool("search_files", "Search a website's files for text",
      "Find which files contain a string, and on which line. Use it to locate "
      "where something is configured, or which file mentions a domain. Skips "
      "dependency trees, caches, uploads and binary files, and says so when "
      "it stopped early rather than pretending it found everything.",
      {"domain": DOMAIN_ARG,
       "text": {"type": "string", "maxLength": 200,
                "description": "The exact string to look for. Not a regular expression."},
       "path": {"type": "string", "maxLength": 1024,
                "description": "Directory to search under, relative to the website "
                               "root. Omit to search the whole site."},
       "max_matches": {"type": "integer", "minimum": 1, "maximum": 100,
                       "description": "Defaults to 100."}},
      required=("domain", "text"))
def _search_files(ctx: Context, args: dict):
    website = _website(ctx, args["domain"])
    try:
        return file_manager.search_text(
            website, args["text"], relative_path=args.get("path", ""),
            max_matches=args.get("max_matches", 100))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
