import csv
import gzip
import hashlib
import ipaddress
import json
import re
import socket
import threading
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from app.core.config import settings
from app.models.entities import Website
from app.services import nginx
from app.services.shell import CommandResult, shell

try:
    import maxminddb
except ImportError:  # pragma: no cover - optional GeoIP support
    maxminddb = None


DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
MAX_CUSTOM_BYTES = 64 * 1024
MAX_SITE_RULE_BYTES = 160 * 1024
# nginx escapes " and control chars in its string vars, so a quoted field never
# contains a bare " - matching with [^"]* keeps this linear. The old
# (?:[^"\\]|\\.)* form backtracked catastrophically on binary/garbage requests
# (TLS handshakes hitting :80, fuzzers), turning a few such lines into seconds.
ACCESS_LOG_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<body_bytes>\S+)'
    r'(?: "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)")?'
    r'(?: (?P<request_time>[0-9.]+))?'
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
GEOIP_COUNTRY_DB_CANDIDATES = (
    "/usr/share/GeoIP/GeoLite2-Country.mmdb",
    "/usr/local/share/GeoIP/GeoLite2-Country.mmdb",
    "/var/lib/GeoIP/GeoLite2-Country.mmdb",
)
DBIP_CACHE_BASENAME = "dbip-country-lite-{year}-{month}.csv.gz"
DBIP_DOWNLOAD_TIMEOUT = 20
COUNTRY_NAMES = {
    "AU": "Australia",
    "BR": "Brazil",
    "CA": "Canada",
    "CN": "China",
    "DE": "Germany",
    "ES": "Spain",
    "FR": "France",
    "GB": "United Kingdom",
    "HK": "Hong Kong",
    "ID": "Indonesia",
    "IN": "India",
    "JP": "Japan",
    "KR": "South Korea",
    "MY": "Malaysia",
    "PH": "Philippines",
    "RU": "Russia",
    "SG": "Singapore",
    "TH": "Thailand",
    "US": "United States",
    "VN": "Vietnam",
    "ZZ": "Unknown",
}

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


def _geoip_country_db_paths() -> list[Path]:
    configured = (settings.geoip_country_db or "").strip()
    if configured:
        return [Path(configured)]
    return [Path(path) for path in GEOIP_COUNTRY_DB_CANDIDATES]


@lru_cache(maxsize=1)
def _geoip_country_reader():
    if maxminddb is None:
        return None
    for path in _geoip_country_db_paths():
        if not path.is_file():
            continue
        try:
            return maxminddb.open_database(str(path))
        except Exception:
            continue
    return None


def _dbip_country_url(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    template = (settings.geoip_dbip_country_url or "").strip()
    if not template:
        return ""
    return template.format(year=f"{current.year:04d}", month=f"{current.month:02d}")


def _dbip_country_cache_path(now: datetime | None = None) -> Path:
    current = now or datetime.now(timezone.utc)
    cache_dir = Path((settings.geoip_dbip_cache_dir or "/var/lib/bpanel/geoip").strip())
    return cache_dir / DBIP_CACHE_BASENAME.format(year=f"{current.year:04d}", month=f"{current.month:02d}")


def _ensure_dbip_country_cache() -> Path | None:
    path = _dbip_country_cache_path()
    if path.is_file():
        return path
    url = _dbip_country_url()
    if not url:
        return None
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"https", "http"}:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "BPanel GeoIP updater"})
        with urllib.request.urlopen(request, timeout=DBIP_DOWNLOAD_TIMEOUT) as response:
            if getattr(response, "status", 200) >= 400:
                return None
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            tmp_path.replace(path)
    except Exception:
        return None
    return path if path.is_file() else None


def _ip_str_to_int(value: str) -> tuple[int, int] | None:
    """(version, integer) for a well-formed IP string, or None.

    Uses socket.inet_pton (C) instead of the ipaddress module: the dbip CSV has
    ~700k rows and ipaddress.ip_address on each start/end pair took ~20-60s to
    build the table on the first access-log view.
    """
    try:
        if ":" in value:
            return 6, int.from_bytes(socket.inet_pton(socket.AF_INET6, value), "big")
        return 4, int.from_bytes(socket.inet_pton(socket.AF_INET, value), "big")
    except OSError:
        return None


_DBIP_WARM_LOCK = threading.Lock()
_DBIP_WARM_STATE = {"started": False, "ready": False}


def _dbip_ranges_ready() -> bool:
    """True once the dbip country table is built.

    Building it parses a ~700k-row CSV (~7-20s cold), so the first call kicks
    the build onto a daemon thread and returns False - an access-log view then
    renders immediately with empty country columns, and later refreshes (the
    response has a short TTL cache) show the geo data once the table is warm.
    """
    if _DBIP_WARM_STATE["ready"]:
        return True
    with _DBIP_WARM_LOCK:
        if _DBIP_WARM_STATE["ready"]:
            return True
        if not _DBIP_WARM_STATE["started"]:
            _DBIP_WARM_STATE["started"] = True

            def _build() -> None:
                try:
                    _dbip_country_ranges()
                finally:
                    _DBIP_WARM_STATE["ready"] = True

            threading.Thread(target=_build, name="bpanel-dbip-warm", daemon=True).start()
    return False


def _warm_dbip_ranges_blocking() -> None:
    """Build the table synchronously (test helper / one-off warmers)."""
    _dbip_country_ranges()
    _DBIP_WARM_STATE["started"] = True
    _DBIP_WARM_STATE["ready"] = True


@lru_cache(maxsize=1)
def _dbip_country_ranges() -> tuple[tuple[tuple[int, int, str], ...], tuple[tuple[int, int, str], ...]]:
    path = _ensure_dbip_country_cache()
    if path is None:
        return (), ()
    ipv4_ranges: list[tuple[int, int, str]] = []
    ipv6_ranges: list[tuple[int, int, str]] = []
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) < 3:
                    continue
                start = _ip_str_to_int(row[0].strip())
                end = _ip_str_to_int(row[1].strip())
                if not start or not end or start[0] != end[0]:
                    continue
                country_code = row[2].strip().upper()
                (ipv4_ranges if start[0] == 4 else ipv6_ranges).append((start[1], end[1], country_code))
    except Exception:
        return (), ()
    ipv4_ranges.sort(key=lambda item: item[0])
    ipv6_ranges.sort(key=lambda item: item[0])
    return tuple(ipv4_ranges), tuple(ipv6_ranges)


def _lookup_dbip_country(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> dict[str, str]:
    if not _dbip_ranges_ready():
        return {"country": "", "country_code": ""}
    ipv4_ranges, ipv6_ranges = _dbip_country_ranges()
    ranges = ipv4_ranges if address.version == 4 else ipv6_ranges
    if not ranges:
        return {"country": "", "country_code": ""}
    value = int(address)
    low = 0
    high = len(ranges) - 1
    while low <= high:
        mid = (low + high) // 2
        start, end, country_code = ranges[mid]
        if value < start:
            high = mid - 1
        elif value > end:
            low = mid + 1
        else:
            if country_code == "ZZ":
                return {"country": "", "country_code": ""}
            return {"country": COUNTRY_NAMES.get(country_code, country_code), "country_code": country_code}
    return {"country": "", "country_code": ""}


def _lookup_ip_country(ip: str) -> dict[str, str]:
    value = (ip or "").strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return {"country": "", "country_code": ""}
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return {"country": "", "country_code": ""}
    dbip_country = _lookup_dbip_country(address)
    if dbip_country["country_code"]:
        return dbip_country
    reader = _geoip_country_reader()
    if reader is None:
        return {"country": "", "country_code": ""}
    try:
        record = reader.get(value) or {}
    except Exception:
        return {"country": "", "country_code": ""}
    country = record.get("country") or record.get("registered_country") or {}
    names = country.get("names") or {}
    country_code = country.get("iso_code") or ""
    return {
        "country": names.get("en") or country_code,
        "country_code": country_code,
    }


def _parse_access_log_line(domain: str, line: str, sequence: int) -> tuple[datetime, dict] | None:
    match = ACCESS_LOG_RE.match(line or "")
    if not match:
        return None
    status_code = int(match.group("status"))
    method, path, protocol = _split_request(match.group("request"))
    timestamp = _parse_nginx_time(match.group("time"))
    sort_time = timestamp or datetime.min.replace(tzinfo=timezone.utc)
    digest = hashlib.sha256(f"{domain}\0{sequence}\0{line}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    ip = match.group("ip") or ""
    country = _lookup_ip_country(ip)
    item = {
        "id": digest,
        "domain": domain,
        "verdict": _access_verdict(status_code),
        "timestamp": timestamp.isoformat() if timestamp else "",
        "duration_ms": _duration_ms(match.group("request_time")),
        "ip": ip,
        "country": country["country"],
        "country_code": country["country_code"],
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
        for key in ("domain", "verdict", "method", "path", "ip", "country", "country_code", "reason", "status", "user_agent", "referer", "protocol", "raw")
    ).lower()
    return needle in haystack


def _read_site_logs(domains: list[str], lines: int) -> dict[str, str | None]:
    """{domain: content} for every site's access log in one helper spawn.

    ``None`` means the file does not exist. Falls back to per-site reads only
    when the batch helper is unavailable (dev).
    """
    if not domains:
        return {}
    result = shell.privileged(
        "site-logs-read-many",
        helper_args=["access", str(lines), *domains],
        check=False,
        fallback=None,
    ) if _batch_helper_available() else None

    if result is None or result.returncode != 0:
        out: dict[str, str | None] = {}
        for domain in domains:
            data = nginx.read_site_log(domain, "access", lines)
            out[domain] = data.get("content") or "" if data.get("exists") else None
        return out

    blocks: dict[str, str | None] = {domain: None for domain in domains}
    for chunk in (result.stdout or "").split("\x1f"):
        if not chunk:
            continue
        head, _, body = chunk.partition("\n")
        domain = head.strip()
        if domain not in blocks:
            continue
        blocks[domain] = None if body.strip() == "BPANEL_LOG_MISSING" else body
    return blocks


def _batch_helper_available() -> bool:
    from app.services.shell import _use_helper

    return _use_helper()


# Reading two dozen nginx logs off a cold disk takes seconds; the page polls
# every few seconds, so the same answer is served from here in between.
_ACCESS_LOG_CACHE: dict[tuple, tuple[float, dict]] = {}
_ACCESS_LOG_TTL = 4.0


def access_logs(
    websites: Iterable[Website],
    *,
    verdict: str = "all",
    query: str = "",
    limit: int = 50,
    lines: int = 5000,
) -> dict:
    import time

    websites = list(websites)
    safe_limit = max(1, min(int(limit or 50), 500))
    safe_lines = max(1, min(int(lines or 5000), 5000))
    safe_verdict = verdict if verdict in {"all", "allow", "block", "error"} else "all"
    filtering = safe_verdict != "all" or bool((query or "").strip())
    # Without a filter the newest `limit` lines per site are all we can show, so
    # there is no reason to tail (and parse) thousands. With a filter we need
    # the deep history to find enough matches.
    scan_lines = safe_lines if filtering else min(safe_lines, max(safe_limit * 4, 400))

    cache_key = (tuple(sorted(w.domain for w in websites)), safe_verdict, (query or "").strip(), safe_limit, scan_lines)
    hit = _ACCESS_LOG_CACHE.get(cache_key)
    if hit and (time.monotonic() - hit[0]) < _ACCESS_LOG_TTL:
        return {**hit[1], "cached": True}

    # Start (once) the background build of the geo table so it overlaps the log
    # read + parse below instead of blocking the first request that needs it.
    _dbip_ranges_ready()

    domains = [_validate_domain(w.domain) for w in websites]
    blocks = _read_site_logs(domains, scan_lines)

    sortable: list[tuple[datetime, int, dict]] = []
    parsed_count = 0
    sequence = 0
    missing: list[str] = []
    for domain in domains:
        content = blocks.get(domain)
        if content is None:
            missing.append(domain)
            continue
        for line in content.splitlines():
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
    payload = {
        "items": items,
        "total": len(sortable),
        "scanned": parsed_count,
        "limit": safe_limit,
        "lines": scan_lines,
        "verdict": safe_verdict,
        "query": (query or "").strip(),
        "missing": missing,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    if len(_ACCESS_LOG_CACHE) > 32:
        _ACCESS_LOG_CACHE.clear()
    _ACCESS_LOG_CACHE[cache_key] = (time.monotonic(), payload)
    return payload


def clear_access_logs(websites: Iterable[Website]) -> int:
    _ACCESS_LOG_CACHE.clear()
    cleared = 0
    for website in websites:
        nginx.clear_site_log(_validate_domain(website.domain), "access")
        cleared += 1
    return cleared
