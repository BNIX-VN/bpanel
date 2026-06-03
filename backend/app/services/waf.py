import json
import re
from typing import Iterable

from app.models.entities import Website
from app.services.shell import CommandResult, shell


DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
MAX_CUSTOM_BYTES = 64 * 1024
MAX_SITE_RULE_BYTES = 160 * 1024

DEFAULT_RULES = [
    {
        "id": "general-sensitive-files",
        "category": "General",
        "title": "Sensitive file probes",
        "description": "Blocks direct probes for env files, git data, composer metadata, PHPUnit, and system files.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/\\.env(?:\\.|$)|/\\.git/|/composer\\.(?:json|lock)|/vendor/phpunit|/etc/passwd|/web\\.config|/config\\.php(?:\\.|$))" "id:1001001,phase:1,deny,status:403,log,msg:'BPanel blocked sensitive file probe'""",
    },
    {
        "id": "general-path-traversal",
        "category": "General",
        "title": "Path traversal",
        "description": "Blocks ../ and encoded traversal probes in URLs, headers, and arguments.",
        "rules": """SecRule REQUEST_URI|ARGS|REQUEST_HEADERS "@rx (?i)(?:\\.\\./|\\.\\.\\\\|%2e%2e%2f|%252e%252e%252f)" "id:1001002,phase:2,deny,status:403,log,msg:'BPanel blocked path traversal'""",
    },
    {
        "id": "general-sqli",
        "category": "General",
        "title": "SQL injection probes",
        "description": "Blocks high-confidence SQL injection primitives.",
        "rules": """SecRule ARGS|REQUEST_HEADERS|REQUEST_BODY "@rx (?i)(?:union\\s+select|sleep\\s*\\(|benchmark\\s*\\(|load_file\\s*\\(|into\\s+outfile|information_schema|extractvalue\\s*\\()" "id:1001003,phase:2,deny,status:403,log,msg:'BPanel blocked SQL injection pattern'""",
    },
    {
        "id": "general-xss",
        "category": "General",
        "title": "XSS probes",
        "description": "Blocks common script injection payloads.",
        "rules": """SecRule ARGS|REQUEST_HEADERS|REQUEST_BODY "@rx (?i)(?:<script|javascript:|onerror\\s*=|onload\\s*=|document\\.cookie|<iframe|base64_decode\\s*\\()" "id:1001004,phase:2,deny,status:403,log,msg:'BPanel blocked XSS pattern'""",
    },
    {
        "id": "general-command-injection",
        "category": "General",
        "title": "Command injection probes",
        "description": "Blocks shell and downloader payloads commonly used for webshell drops.",
        "rules": """SecRule ARGS|REQUEST_HEADERS|REQUEST_BODY "@rx (?i)(?:/bin/(?:bash|sh)|cmd\\.exe|powershell|wget\\s+https?://|curl\\s+https?://|;\\s*(?:id|whoami|uname)\\b)" "id:1001005,phase:2,deny,status:403,log,msg:'BPanel blocked command injection pattern'""",
    },
    {
        "id": "wordpress-sensitive-files",
        "category": "WordPress",
        "title": "WordPress sensitive files",
        "description": "Blocks wp-config, readme/license probes, uploads PHP execution probes, and internal WordPress PHP paths.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/wp-config\\.php|/readme\\.html|/license\\.txt|/wp-content/(?:uploads|cache|upgrade)/.*\\.php|/wp-admin/includes/.*\\.php|/wp-includes/.*\\.php)" "id:1001101,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress sensitive path'""",
    },
    {
        "id": "wordpress-xmlrpc-author-scan",
        "category": "WordPress",
        "title": "WordPress XML-RPC and author scans",
        "description": "Blocks XML-RPC requests and ?author= enumeration scans.",
        "rules": """SecRule REQUEST_URI "@streq /xmlrpc.php" "id:1001102,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress XML-RPC'"
SecRule ARGS:author "@rx ^[0-9]+$" "id:1001103,phase:2,deny,status:403,log,msg:'BPanel blocked WordPress author enumeration'""",
    },
    {
        "id": "wordpress-install-upgrade",
        "category": "WordPress",
        "title": "WordPress installer probes",
        "description": "Blocks direct access to installation and upgrade scripts after deployment.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/wp-admin/install\\.php|/wp-admin/upgrade\\.php|/wp-admin/setup-config\\.php)" "id:1001104,phase:1,deny,status:403,log,msg:'BPanel blocked WordPress installer probe'""",
    },
    {
        "id": "laravel-sensitive-files",
        "category": "Laravel",
        "title": "Laravel sensitive paths",
        "description": "Blocks .env, artisan, vendor, storage, and bootstrap cache probes.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:^/(?:artisan|server\\.php)$|/\\.env(?:\\.|$)|/vendor/|/storage/(?:logs|framework|app)/|/bootstrap/cache/)" "id:1001201,phase:1,deny,status:403,log,msg:'BPanel blocked Laravel sensitive path'""",
    },
    {
        "id": "laravel-debug-rce",
        "category": "Laravel",
        "title": "Laravel debug/RCE probes",
        "description": "Blocks common Ignition/debug and PHP stream wrapper exploit payloads.",
        "rules": """SecRule REQUEST_URI|ARGS|REQUEST_BODY "@rx (?i)(?:_ignition/execute-solution|_debugbar|php://filter|phar://|expect://|data://)" "id:1001202,phase:2,deny,status:403,log,msg:'BPanel blocked Laravel debug/RCE probe'""",
    },
    {
        "id": "whmcs-sensitive-files",
        "category": "WHMCS",
        "title": "WHMCS sensitive files",
        "description": "Blocks configuration, attachments, downloads, and template cache probes.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/configuration\\.php|/(?:attachments|downloads|templates_c|crons)/(?:.*\\.php|.*)?|/vendor/|/install/)" "id:1001301,phase:1,deny,status:403,log,msg:'BPanel blocked WHMCS sensitive path'""",
    },
    {
        "id": "whmcs-admin-probes",
        "category": "WHMCS",
        "title": "WHMCS admin/install probes",
        "description": "Blocks common WHMCS installer and admin utility probes.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/(?:admin|admincp|whmcs-admin)/(?:setup|install|upgrade)|/modules/.*/(?:callback|hook)\\.php\\.bak)" "id:1001302,phase:1,deny,status:403,log,msg:'BPanel blocked WHMCS admin probe'""",
    },
    {
        "id": "codeigniter-sensitive-paths",
        "category": "CodeIgniter",
        "title": "CodeIgniter sensitive paths",
        "description": "Blocks application, system, writable, cache, and log paths.",
        "rules": """SecRule REQUEST_URI "@rx (?i)(?:/(?:application|system)/(?:config|logs|cache|core|helpers|libraries)/|/writable/(?:logs|cache|session|uploads)/|/app/Config/)" "id:1001401,phase:1,deny,status:403,log,msg:'BPanel blocked CodeIgniter sensitive path'""",
    },
    {
        "id": "codeigniter-env-debug",
        "category": "CodeIgniter",
        "title": "CodeIgniter env/debug probes",
        "description": "Blocks env files, debug toolbar, and profiler probes.",
        "rules": """SecRule REQUEST_URI|ARGS "@rx (?i)(?:/\\.env|/index\\.php/_debugbar|/index\\.php/profiler|CI_ENVIRONMENT\\s*=)" "id:1001402,phase:2,deny,status:403,log,msg:'BPanel blocked CodeIgniter env/debug probe'""",
    },
]


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
    selected = {str(item) for item in raw if str(item) in valid}
    return selected


def validate_enabled_rule_ids(rule_ids: Iterable[str]) -> list[str]:
    valid = _rule_ids()
    selected = []
    for rule_id in rule_ids:
        value = str(rule_id)
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
