import ipaddress
import re
from typing import Optional

from app.core.config import settings
from app.services.shell import CommandResult, shell


PORT_RE = re.compile(r"^[0-9]{1,5}$")
PROTOCOLS = {"tcp", "udp"}
NUMBERED_RULE_RE = re.compile(r"^\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)\s+(IN|OUT)\s+(.+)$", re.I)


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
            "number": int(number),
            "to": to_value.strip(),
            "action": action.upper(),
            "direction": direction.upper(),
            "from": from_value.strip(),
        }
        rule["protected"] = is_protected_rule(rule)
        rules.append(rule)
    return rules


def is_protected_rule(rule: dict) -> bool:
    if (rule.get("action") or "").upper() != "ALLOW":
        return False
    target = (rule.get("to") or "").lower()
    if "openssh" in target or "nginx full" in target:
        return True
    protected_ports = {22, 80, 443, int(settings.panel_port or 2222)}
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
        raise ValueError("Default SSH, web, and panel firewall rules cannot be deleted")
    return shell.privileged(
        "ufw-delete",
        helper_args=[str(number)],
        fallback=["ufw", "--force", "delete", str(number)],
    )
