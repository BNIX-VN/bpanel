from app.services.shell import shell


def _validate_custom_rules(content: str) -> str:
    value = content or ""
    if "\x00" in value:
        raise ValueError("WAF rules cannot contain NUL bytes")
    if len(value.encode("utf-8")) > 64 * 1024:
        raise ValueError("WAF custom rules must be 64 KB or smaller")
    return value.replace("\r\n", "\n")


def status():
    return shell.privileged(
        "waf-status",
        check=False,
        fallback=["bash", "-lc", "test -f /etc/nginx/modsec/bpanel-main.conf && echo installed || echo not-installed"],
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
