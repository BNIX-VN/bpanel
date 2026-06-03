import ipaddress
import re
from typing import Optional

from app.core.config import settings
from app.services.shell import CommandResult, shell


PORT_RE = re.compile(r"^[0-9]{1,5}$")
PROTOCOLS = {"tcp", "udp"}
NUMBERED_RULE_RE = re.compile(r"^\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)\s+(IN|OUT)\s+(.+)$", re.I)
DEFAULT_PROTECTED_PORTS = {22, 80, 443, 465, 587, 2222}
PANEL_ZONE = "PanelZone"
USER_ZONE = "UserZone"


def _strip_zone_comment(value: str) -> str:
    return re.sub(r"\s*(?:#|\()?\s*bpanel:(?:PanelZone|UserZone)(?::[A-Za-z0-9_-]+)?\)?", "", value, flags=re.I).strip()


def _zone_from_values(*values: str) -> str | None:
    joined = " ".join(values).lower()
    if "bpanel:panelzone" in joined:
        return PANEL_ZONE
    if "bpanel:userzone" in joined:
        return USER_ZONE
    return None


def _validate_protocol(protocol: str) -> str:
    value = (protocol or "tcp").strip().lower()
    if value not in PROTOCOLS:
        raise ValueError("Protocol must be tcp or udp")
    return value


def _validate_port(port: str | int) -> str:
    value = str(port).strip()
    if not PORT_RE.match(value):
        raise ValueError("Port must be a number from 1 to 65535")
    number = int(value)
    if number < 1 or number > 65535:
        raise ValueError("Port must be a number from 1 to 65535")
    return value


def _validate_network(network: str) -> str:
    value = network.strip()
    try:
        parsed = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError("IP must be a valid IPv4/IPv6 address or CIDR network") from exc
    return str(parsed)


def status() -> CommandResult:
    return shell.privileged("ufw-status", check=False, fallback=["ufw", "status", "numbered"])


def parse_numbered_rules(output: str) -> list[dict]:
    rules = []
    for line in (output or "").splitlines():
        match = NUMBERED_RULE_RE.match(line.strip())
        if not match:
            continue
        number, to_value, action, direction, from_value = match.groups()
        rule = {
            "id": int(number),
            "number": int(number),
            "to": _strip_zone_comment(to_value),
            "action": action.upper(),
            "direction": direction.upper(),
            "from": _strip_zone_comment(from_value),
        }
        protected_default = is_protected_rule(rule)
        explicit_zone = _zone_from_values(to_value, from_value)
        rule["zone"] = explicit_zone or (PANEL_ZONE if protected_default else USER_ZONE)
        rule["protected"] = rule["zone"] == PANEL_ZONE
        rules.append(rule)
    return rules


def is_protected_rule(rule: dict) -> bool:
    if (rule.get("action") or "").upper() != "ALLOW":
        return False
    target = (rule.get("to") or "").lower()
    if "openssh" in target or "nginx full" in target or "nginx http" in target or "nginx https" in target:
        return True
    protected_ports = set(DEFAULT_PROTECTED_PORTS)
    try:
        protected_ports.add(int(settings.panel_port or 2222))
    except (TypeError, ValueError):
        pass
    for value in re.findall(r"\d{1,5}", target):
        try:
            if int(value) in protected_ports:
                return True
        except ValueError:
            continue
    return False


def enable() -> CommandResult:
    return shell.privileged("ufw-enable", fallback=["ufw", "--force", "enable"])


def disable() -> CommandResult:
    return shell.privileged("ufw-disable", fallback=["ufw", "--force", "disable"])


def reload() -> CommandResult:
    return shell.privileged("ufw-reload", fallback=["ufw", "reload"])


def allow_port(port: str | int, protocol: str = "tcp") -> CommandResult:
    clean_port = _validate_port(port)
    clean_protocol = _validate_protocol(protocol)
    return shell.privileged(
        "ufw-allow-port",
        helper_args=[clean_port, clean_protocol],
        fallback=["ufw", "allow", f"{clean_port}/{clean_protocol}"],
    )


def allow_ip(network: str, port: Optional[str | int] = None, protocol: str = "tcp") -> CommandResult:
    clean_network = _validate_network(network)
    if not port:
        return shell.privileged(
            "ufw-allow-ip",
            helper_args=[clean_network],
            fallback=["ufw", "allow", "from", clean_network],
        )
    clean_port = _validate_port(port)
    clean_protocol = _validate_protocol(protocol)
    return shell.privileged(
        "ufw-allow-ip",
        helper_args=[clean_network, clean_port, clean_protocol],
        fallback=["ufw", "allow", "from", clean_network, "to", "any", "port", clean_port, "proto", clean_protocol],
    )


def block_ip(network: str, port: Optional[str | int] = None, protocol: str = "tcp") -> CommandResult:
    clean_network = _validate_network(network)
    if not port:
        return shell.privileged(
            "ufw-deny-ip",
            helper_args=[clean_network],
            fallback=["ufw", "deny", "from", clean_network],
        )
    clean_port = _validate_port(port)
    clean_protocol = _validate_protocol(protocol)
    return shell.privileged(
        "ufw-deny-ip",
        helper_args=[clean_network, clean_port, clean_protocol],
        fallback=["ufw", "deny", "from", clean_network, "to", "any", "port", clean_port, "proto", clean_protocol],
    )


def delete_rule(number: int) -> CommandResult:
    if number < 1:
        raise ValueError("Rule number must be greater than 0")
    rules = parse_numbered_rules(status().stdout)
    selected = next((rule for rule in rules if rule["number"] == number), None)
    if selected and selected.get("protected"):
        raise ValueError("Default panel, mail, web, and SSH firewall rules cannot be deleted")
    return shell.privileged(
        "ufw-delete",
        helper_args=[str(number)],
        fallback=["ufw", "--force", "delete", str(number)],
    )


def blocklists() -> CommandResult:
    return shell.privileged(
        "ufw-blocklist-status",
        check=False,
        fallback=["bash", "-lc", "echo 'URLs:'; cat /tmp/bpanel-firewall-blocklists.urls 2>/dev/null || true"],
    )


def add_blocklist_url(url: str) -> CommandResult:
    return shell.privileged(
        "ufw-blocklist-add",
        helper_args=[url],
        check=False,
        fallback=["bash", "-lc", "echo URL added"],
    )


def delete_blocklist_url(url: str) -> CommandResult:
    return shell.privileged(
        "ufw-blocklist-delete",
        helper_args=[url],
        check=False,
        fallback=["bash", "-lc", "echo URL removed"],
    )


def update_blocklists() -> CommandResult:
    return shell.privileged(
        "ufw-blocklist-run",
        check=False,
        fallback=["bash", "-lc", "echo blocklist update skipped"],
    )
