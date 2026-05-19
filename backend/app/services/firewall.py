import ipaddress
import re
from typing import Optional

from app.services.shell import CommandResult, shell


PORT_RE = re.compile(r"^[0-9]{1,5}$")
PROTOCOLS = {"tcp", "udp"}


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
    return shell.run(["ufw", "status", "verbose", "numbered"], check=False)


def enable() -> CommandResult:
    return shell.run(["ufw", "--force", "enable"])


def disable() -> CommandResult:
    return shell.run(["ufw", "--force", "disable"])


def reload() -> CommandResult:
    return shell.run(["ufw", "reload"])


def allow_port(port: str | int, protocol: str = "tcp") -> CommandResult:
    clean_port = _validate_port(port)
    clean_protocol = _validate_protocol(protocol)
    return shell.run(["ufw", "allow", f"{clean_port}/{clean_protocol}"])


def allow_ip(network: str, port: Optional[str | int] = None, protocol: str = "tcp") -> CommandResult:
    clean_network = _validate_network(network)
    if not port:
        return shell.run(["ufw", "allow", "from", clean_network])
    clean_port = _validate_port(port)
    clean_protocol = _validate_protocol(protocol)
    return shell.run(["ufw", "allow", "from", clean_network, "to", "any", "port", clean_port, "proto", clean_protocol])


def block_ip(network: str, port: Optional[str | int] = None, protocol: str = "tcp") -> CommandResult:
    clean_network = _validate_network(network)
    if not port:
        return shell.run(["ufw", "deny", "from", clean_network])
    clean_port = _validate_port(port)
    clean_protocol = _validate_protocol(protocol)
    return shell.run(["ufw", "deny", "from", clean_network, "to", "any", "port", clean_port, "proto", clean_protocol])


def delete_rule(number: int) -> CommandResult:
    if number < 1:
        raise ValueError("Rule number must be greater than 0")
    return shell.run(["ufw", "--force", "delete", str(number)])
