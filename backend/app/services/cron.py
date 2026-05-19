import re
import shlex

from app.models.entities import Website
from app.services.shell import shell


CRON_FIELD_RE = r"(?:\*|\d{1,2})(?:[-/,](?:\*|\d{1,2}))*"
DOMAIN_GREP_RE = re.compile(r"^[a-z0-9.\-]{3,253}$")
ALLOWED_COMMAND_PREFIXES = (
    ("wp", "cron", "event", "run", "--due-now"),
    ("wp", "core", "update"),
    ("wp", "plugin", "update", "--all"),
    ("wp", "theme", "update", "--all"),
)


def _validate_schedule(schedule: str) -> str:
    fields = schedule.split()
    if len(fields) != 5 or not all(re.fullmatch(CRON_FIELD_RE, field) for field in fields):
        raise ValueError("Invalid cron schedule")
    return " ".join(fields)


def _validate_domain(domain: str) -> str:
    value = (domain or "").lower()
    if not DOMAIN_GREP_RE.fullmatch(value):
        raise ValueError("Invalid domain")
    return value


def _validate_command(command: str) -> str:
    args = shlex.split(command)
    if not args:
        raise ValueError("Cron command is required")
    normalized = [arg for arg in args if arg != "--allow-root"]
    if not any(tuple(normalized[:len(prefix)]) == prefix for prefix in ALLOWED_COMMAND_PREFIXES):
        raise ValueError("Only safe WP-CLI maintenance commands are allowed")
    return " ".join(shlex.quote(arg) for arg in [*normalized, "--allow-root"])


def add_cron(website: Website, schedule: str, command: str) -> str:
    safe_schedule = _validate_schedule(schedule)
    safe_command = _validate_command(command)
    safe_domain = _validate_domain(website.domain)
    marker = f"# bpanel:{safe_domain}"
    line = f"{safe_schedule} cd {shlex.quote(website.root_path + '/public')} && {safe_command} {marker}"
    script = f"(crontab -l 2>/dev/null; echo {shlex.quote(line)}) | crontab -"
    shell.run(["bash", "-lc", script])
    return line


def list_cron(domain: str) -> str:
    safe_domain = _validate_domain(domain)
    result = shell.run(
        ["bash", "-lc", f"crontab -l 2>/dev/null | grep -F {shlex.quote('bpanel:' + safe_domain)} || true"],
        check=False,
    )
    return result.stdout


def delete_cron(domain: str, index: int) -> str:
    safe_domain = _validate_domain(domain)
    lines = list_cron(safe_domain).splitlines()
    if index < 0 or index >= len(lines):
        raise ValueError("Cron not found")
    target = lines[index]
    script = f"crontab -l 2>/dev/null | grep -Fv {shlex.quote(target)} | crontab -"
    shell.run(["bash", "-lc", script])
    return target
