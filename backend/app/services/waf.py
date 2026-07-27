import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Iterable

from app.models.entities import Website
from app.services import nginx
from app.services.shell import CommandResult, shell


DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
MAX_CUSTOM_BYTES = 64 * 1024
MAX_SITE_RULE_BYTES = 160 * 1024
ACCESS_LOG_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<request>(?:[^"\\]|\\.)*)" (?P<status>\d{3}) (?P<body_bytes>\S+)'
    r'(?: "(?P<referer>(?:[^"\\]|\\.)*)" "(?P<user_agent>(?:[^"\\]|\\.)*)")?'
    r'(?: (?P<request_time>[0-9.]+))?.*$'
)
ACCESS_REASON_RULES = [
    (re.compile(r"(?:^|/)\.env(?:\.|$|[?])", re.I), "Block environment file probe"),
    (re.compile(r"(?:^|/)\.git/", re.I), "Block git metadata probe"),
    (re.compile(r"/composer\.(?:json|lock)(?:$|[?])", re.I), "Block Composer metadata probe"),
    (re.compile(r"/wp-config\.php(?:\.|$|[?])", re.I), "Block WordPress config probe"),
    (re.compile(r"/wp-content/(?:uploads|cache|upgrade)/[^?]*\.php(?:$|[?])", re.I), "Block WordPress upload PHP probe"),
    (re.compile(r"/wp-admin/(?:install|setup-config)\.php(?:$|[?])", re.I), "Block WordPress installer probe"),
    (re.compile(r"[?&]author=[0-9]+(?:&|$)", re.I), "Block WordPress author scan"),
    (re.compile(r"/_ignition/execute-solution(?:$|[?])", re.I), "Block Laravel Ignition RCE probe"),
    (re.compile(r"/(?:artisan|server\.php)(?:$|[?])", re.I), "Block Laravel runtime probe"),
    (re.compile(r"/storage/logs/[^?]*\.log(?:$|[?])", re.I), "Block Laravel log probe"),
    (re.compile(r"(?:\.\./|\.\.\\|%2e%2e%2f|%252e%252e%252f)", re.I), "Block path traversal"),
    (re.compile(r"/(?:c99|r57|shell|cmd|wso)\.php(?:$|[?])", re.I), "Block PHP runtime probe"),
]

DEFAULT_RULES = [
    {
        "id": "php-sensitive-files",
        "category": "PHP",
        "title": "PHP sensitive files",
        "description": "Blocks direct probes for PHP app secrets, Composer metadata, git data, and phpinfo files.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/\\.env(?:\\.|$)|/\\.user\\.ini(?:\\.|$)|/\\.git/|/composer\\.(?:json|lock)(?:$|[?])|/(?:phpinfo|info)\\.php(?:$|[?])|/(?:config|database|db)\\.php\\.(?:bak|old|save|txt)(?:$|[?]))" "id:1001301,phase:1,deny,status:403,log,msg:'BPanel blocked PHP sensitive file probe'""",
    },
    {
        "id": "php-path-traversal",
        "category": "PHP",
        "title": "Path traversal",
        "description": "Blocks ../ and encoded traversal probes in URLs and query/form arguments.",
        "rules": """SecRule REQUEST_URI|ARGS "@rx (?i)(?:\\.\\./|\\.\\.\\\\|%2e%2e%2f|%252e%252e%252f)" "id:1001302,phase:2,deny,status:403,log,msg:'BPanel blocked PHP path traversal'""",
    },
    {
        "id": "php-runtime-probes",
        "category": "PHP",
        "title": "PHP runtime probes",
        "description": "Blocks direct probes for common PHP webshell names and old PHPUnit RCE paths.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/(?:c99|r57|shell|cmd|wso)\\.php(?:$|[?])|/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin\\.php(?:$|[?]))" "id:1001303,phase:1,deny,status:403,log,msg:'BPanel blocked PHP runtime probe'""",
    },
    {
        "id": "laravel-sensitive-files",
        "category": "Laravel",
        "title": "Laravel sensitive files",
        "description": "Blocks probes for Laravel environment files, logs, artisan, and cached PHP config.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/\\.env(?:\\.|$)|/artisan(?:$|[?])|/server\\.php(?:$|[?])|/storage/logs/[^?]*\\.log(?:$|[?])|/bootstrap/cache/[^?]*\\.php(?:$|[?]))" "id:1001201,phase:1,deny,status:403,log,msg:'BPanel blocked Laravel sensitive path'""",
    },
    {
        "id": "laravel-ignition-rce",
        "category": "Laravel",
        "title": "Laravel Ignition RCE probes",
        "description": "Blocks direct probes for the old Laravel Ignition execute-solution endpoint.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/_ignition/execute-solution(?:$|[?]))" "id:1001202,phase:1,deny,status:403,log,msg:'BPanel blocked Laravel Ignition RCE probe'""",
    },
    {
        "id": "wordpress-sensitive-files",
        "category": "WordPress",
        "title": "WordPress sensitive files",
        "description": "Blocks wp-config probes, uploads PHP execution probes, and internal WordPress PHP paths.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/wp-config\\.php(?:\\.|$|[?])|/wp-content/(?:uploads|cache|upgrade)/[^?]*\\.php(?:$|[?])|/wp-admin/includes/[^?]*\\.php(?:$|[?])|/wp-includes/[^?]*\\.php(?:$|[?]))" "id:1001101,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress sensitive path'""",
    },
    {
        "id": "wordpress-xmlrpc-author-scan",
        "category": "WordPress",
        "title": "WordPress author scans",
        "description": "Blocks ?author= enumeration scans while leaving XML-RPC compatibility to site policy.",
        "rules": """SecRule ARGS:author "@rx ^[0-9]+$" "id:1001103,phase:2,deny,status:403,log,msg:'BPanel blocked WordPress author enumeration'""",
    },
    {
        "id": "wordpress-install-upgrade",
        "category": "WordPress",
        "title": "WordPress installer probes",
        "description": "Blocks direct access to WordPress installation scripts after deployment.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/wp-admin/install\\.php(?:$|[?])|/wp-admin/setup-config\\.php(?:$|[?]))" "id:1001104,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress installer probe'""",
    },
]

LEGACY_RULE_ID_MAP = {
    "general-sensitive-files": "php-sensitive-files",
    "general-path-traversal": "php-path-traversal",
    "general-command-injection": "php-runtime-probes",
    "general-sqli": None,
    "general-xss": None,
}


def _rule_ids() -> set[str]:
    return {rule["id"] for rule in DEFAULT_RULES}


def _validate_domain(domain: str) -> str:
    value = (domain or "").strip().lower()
    if not DOMAIN_RE.fullmatch(value):
        raise ValueError("Invalid domain")
    return value


def _validate_custom_rules(content: str) -> str:
    value = content or ""
    if "\x00" in value:
        raise ValueError("WAF rules cannot contain NUL bytes")
    if len(value.encode("utf-8")) > MAX_CUSTOM_BYTES:
        raise ValueError("WAF custom rules must be 64 KB or smaller")
    return value.replace("\r\n", "\n").strip()


def _parse_enabled_rule_ids(value: str | None) -> set[str]:
    valid = _rule_ids()
    if not value:
        return set(valid)
    try:
        raw = json.loads(value)
    except (TypeError, ValueError):
        return set(valid)
    if not isinstance(raw, list):
        return set(valid)
    selected = {
        LEGACY_RULE_ID_MAP.get(rule_id, rule_id)
        for item in raw
        for rule_id in [str(item)]
        if LEGACY_RULE_ID_MAP.get(rule_id, rule_id) in valid
    }
    return selected


def validate_enabled_rule_ids(rule_ids: Iterable[str]) -> list[str]:
    valid = _rule_ids()
    selected = []
    for rule_id in rule_ids:
        value = LEGACY_RULE_ID_MAP.get(str(rule_id), str(rule_id))
        if value is None:
            continue
        if value not in valid:
            raise ValueError(f"Unknown WAF rule: {value}")
        if value not in selected:
            selected.append(value)
    return selected


def default_rule_definitions() -> list[dict]:
    return [
        {
            "id": rule["id"],
            "category": rule["category"],
            "title": rule["title"],
            "description": rule["description"],
            "enabled_default": True,
        }
        for rule in DEFAULT_RULES
    ]


def site_rules_file(domain: str) -> str:
    safe_domain = _validate_domain(domain)
    return f"/etc/nginx/modsec/sites/{safe_domain}.conf"


def render_site_rules(domain: str, enabled_rule_ids: Iterable[str], custom_rules: str = "") -> str:
    safe_domain = _validate_domain(domain)
    enabled = set(validate_enabled_rule_ids(enabled_rule_ids))
    custom = _validate_custom_rules(custom_rules)
    chunks = [
        f"# BPanel WAF rules for {safe_domain}",
        "Include /etc/nginx/modsec/bpanel-base.conf",
        "",
        "# BPanel selected default rules",
    ]
    for rule in DEFAULT_RULES:
        if rule["id"] not in enabled:
            continue
        chunks.append(f"# {rule['category']} - {rule['title']} ({rule['id']})")
        chunks.append(rule["rules"].strip())
        if rule.get("exceptions"):
            chunks.append(rule["exceptions"].strip())
    chunks.extend(["", "# BPanel custom rules"])
    if custom:
        chunks.append(custom)
    content = "\n".join(chunks).strip() + "\n"
    if len(content.encode("utf-8")) > MAX_SITE_RULE_BYTES:
        raise ValueError("WAF site rules are too large")
    return content


def website_enabled_rule_ids(website: Website) -> set[str]:
    return _parse_enabled_rule_ids(getattr(website, "waf_default_rules", ""))


def website_custom_rules(website: Website) -> str:
    return _validate_custom_rules(getattr(website, "waf_custom_rules", "") or "")


def sync_site_rules(domain: str, enabled_rule_ids: Iterable[str], custom_rules: str = "") -> CommandResult:
    safe_domain = _validate_domain(domain)
    content = render_site_rules(safe_domain, enabled_rule_ids, custom_rules)
    return shell.privileged(
        "waf-site-save",
        helper_args=[safe_domain],
        check=False,
        input=content,
        fallback=["bash", "-lc", "cat >/tmp/bpanel-waf-site.conf && echo WAF site rules saved"],
    )


def sync_website_rules(website: Website) -> CommandResult:
    return sync_site_rules(website.domain, website_enabled_rule_ids(website), website_custom_rules(website))


def site_config(website: Website) -> dict:
    from app.services import nginx

    enabled = website_enabled_rule_ids(website)
    return {
        "website_id": website.id,
        "domain": website.domain,
        "waf_enabled": bool(website.waf_enabled),
        "http_flood_enabled": bool(getattr(website, "http_flood_enabled", False)),
        "http_flood_config": nginx.http_flood_config_for_website(website),
        "rules_file": site_rules_file(website.domain),
        "default_rules": [
            {
                **rule,
                "enabled": rule["id"] in enabled,
                "enabled_default": True,
            }
            for rule in default_rule_definitions()
        ],
        "enabled_rule_ids": [rule["id"] for rule in DEFAULT_RULES if rule["id"] in enabled],
        "custom_rules": website_custom_rules(website),
    }


def save_website_config(website: Website, enabled_rule_ids: Iterable[str], custom_rules: str) -> CommandResult:
    selected = validate_enabled_rule_ids(enabled_rule_ids)
    custom = _validate_custom_rules(custom_rules)
    website.waf_default_rules = json.dumps(selected, ensure_ascii=True)
    website.waf_custom_rules = custom
    return sync_site_rules(website.domain, selected, custom)


def status():
    return shell.privileged(
        "waf-status",
        check=False,
        fallback=["bash", "-lc", "test -f /etc/nginx/modsec/bpanel-base.conf && echo installed || echo not-installed"],
    )


def install_engine():
    return shell.privileged(
        "waf-install",
        check=False,
        fallback=["bash", "-lc", "apt-get update && apt-get install -y libnginx-mod-http-modsecurity modsecurity-crs"],
    )


def update_rules():
    return shell.privileged(
        "waf-update",
        check=False,
        fallback=["bash", "-lc", "echo no WAF updater found"],
    )


def default_rules():
    return shell.privileged(
        "waf-default-rules",
        check=False,
        fallback=["bash", "-lc", "cat /etc/nginx/modsec/bpanel-default.conf 2>/dev/null || true"],
    )


def custom_rules():
    return shell.privileged(
        "waf-custom-rules",
        check=False,
        fallback=["bash", "-lc", "cat /etc/nginx/modsec/bpanel-custom.conf 2>/dev/null || true"],
    )


def save_custom_rules(content: str):
    return shell.privileged(
        "waf-custom-save",
        check=False,
        input=_validate_custom_rules(content),
        fallback=["bash", "-lc", "cat >/tmp/bpanel-waf-custom.conf && echo WAF custom rules saved"],
    )


def _parse_nginx_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d/%b/%Y:%H:%M:%S %z")
    except (TypeError, ValueError):
        return None


def _split_request(value: str) -> tuple[str, str, str]:
    parts = (value or "").split()
    if len(parts) >= 3:
        return parts[0].upper(), parts[1], parts[2]
    if len(parts) == 2:
        return parts[0].upper(), parts[1], ""
    return "", value or "", ""


def _access_verdict(status_code: int) -> str:
    if status_code in {401, 403, 429, 444}:
        return "block"
    if status_code >= 500:
        return "error"
    return "allow"


def _access_reason(path: str, status_code: int) -> str:
    verdict = _access_verdict(status_code)
    if verdict == "allow":
        return "Allowed"
    if status_code == 429:
        return "HTTP flood rate limit"
    for pattern, reason in ACCESS_REASON_RULES:
        if pattern.search(path or ""):
            return reason
    if status_code == 403:
        return "Blocked by WAF or Nginx"
    if verdict == "error":
        return "Upstream/server error"
    return "Blocked"


def _duration_ms(value: str | None) -> int:
    try:
        return max(0, round(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def _parse_access_log_line(domain: str, line: str, sequence: int) -> tuple[datetime, dict] | None:
    match = ACCESS_LOG_RE.match(line or "")
    if not match:
        return None
    status_code = int(match.group("status"))
    method, path, protocol = _split_request(match.group("request"))
    timestamp = _parse_nginx_time(match.group("time"))
    sort_time = timestamp or datetime.min.replace(tzinfo=timezone.utc)
    digest = hashlib.sha256(f"{domain}\0{sequence}\0{line}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    item = {
        "id": digest,
        "domain": domain,
        "verdict": _access_verdict(status_code),
        "timestamp": timestamp.isoformat() if timestamp else "",
        "duration_ms": _duration_ms(match.group("request_time")),
        "ip": match.group("ip") or "",
        "method": method,
        "path": path,
        "protocol": protocol,
        "status": status_code,
        "reason": _access_reason(path, status_code),
        "user_agent": match.group("user_agent") or "",
        "referer": match.group("referer") or "",
        "raw": line,
    }
    return sort_time, item


def _matches_access_filter(item: dict, verdict: str, query: str) -> bool:
    if verdict and verdict != "all" and item.get("verdict") != verdict:
        return False
    needle = (query or "").strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        str(item.get(key, ""))
        for key in ("domain", "verdict", "method", "path", "ip", "reason", "status", "user_agent", "referer", "protocol", "raw")
    ).lower()
    return needle in haystack


def access_logs(
    websites: Iterable[Website],
    *,
    verdict: str = "all",
    query: str = "",
    limit: int = 50,
    lines: int = 5000,
) -> dict:
    safe_limit = max(1, min(int(limit or 50), 500))
    safe_lines = max(1, min(int(lines or 5000), 5000))
    safe_verdict = verdict if verdict in {"all", "allow", "block", "error"} else "all"
    sortable: list[tuple[datetime, int, dict]] = []
    parsed_count = 0
    sequence = 0
    missing: list[str] = []
    for website in websites:
        domain = _validate_domain(website.domain)
        log_data = nginx.read_site_log(domain, "access", safe_lines)
        if not log_data.get("exists"):
            missing.append(domain)
            continue
        for line in (log_data.get("content") or "").splitlines():
            sequence += 1
            parsed = _parse_access_log_line(domain, line, sequence)
            if not parsed:
                continue
            parsed_count += 1
            sort_time, item = parsed
            if _matches_access_filter(item, safe_verdict, query):
                sortable.append((sort_time, parsed_count, item))
    sortable.sort(key=lambda row: (row[0], row[1]), reverse=True)
    items = [item for _, _, item in sortable[:safe_limit]]
    return {
        "items": items,
        "total": len(sortable),
        "scanned": parsed_count,
        "limit": safe_limit,
        "lines": safe_lines,
        "verdict": safe_verdict,
        "query": (query or "").strip(),
        "missing": missing,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def clear_access_logs(websites: Iterable[Website]) -> int:
    cleared = 0
    for website in websites:
        nginx.clear_site_log(_validate_domain(website.domain), "access")
        cleared += 1
    return cleared
