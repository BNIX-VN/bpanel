"""Start the panel.

uvicorn's command line takes exactly one certificate. The panel needs one per
hostname, so the server is built here instead: the same configuration the
command line would have produced, plus the SNI callback that answers each
handshake with the certificate for the name the browser asked for.

Everything is read from the environment, which systemd fills from
/opt/bpanel/backend/.env:

    PANEL_PORT        port to listen on (default 2222)
    PANEL_SSL_CERT    default certificate, used for hostnames without one
    PANEL_SSL_KEY     its private key
    PANEL_SNI_DIR     where the helper keeps the per-hostname certificates
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path

import uvicorn
from uvicorn.config import create_ssl_context

from app.core import panel_sni
from app.services import panel_ipv6

logger = logging.getLogger("bpanel")

# Only the local Nginx may set X-Forwarded-For / X-Forwarded-Proto. A direct
# hit on the panel port cannot spoof the audit log IP or the rate-limit key.
TRUSTED_FORWARDERS = "127.0.0.1"


def _host() -> str:
    """:: covers IPv4 as well on a dual-stack machine, 0.0.0.0 does not.

    The bind is tried before it is chosen: a server whose IPv6 went away with
    the switch left on must still start, on IPv4, rather than fail to boot and
    take the panel with it.
    """
    if not panel_ipv6.is_enabled():
        return "0.0.0.0"
    # With bindv6only set, a :: socket refuses IPv4 outright. Reaching the panel
    # over IPv4 matters more than reaching it over IPv6, so stay where we are.
    try:
        if Path("/proc/sys/net/ipv6/bindv6only").read_text(encoding="utf-8").strip() == "1":
            logger.warning("net.ipv6.bindv6only is set; listening on IPv4 only")
            return "0.0.0.0"
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        logger.warning("IPv6 is switched on but this machine has no IPv6; listening on IPv4 only")
        return "0.0.0.0"
    with probe:
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("::", 0))
        except OSError:
            logger.warning("IPv6 is switched on but binding :: failed; listening on IPv4 only")
            return "0.0.0.0"
    return "::"


def _port() -> int:
    try:
        return int(os.environ.get("PANEL_PORT") or 2222)
    except ValueError:
        return 2222


def _certificate_pair() -> tuple[str, str] | None:
    cert = (os.environ.get("PANEL_SSL_CERT") or "").strip()
    key = (os.environ.get("PANEL_SSL_KEY") or "").strip()
    if cert and key and Path(cert).is_file() and Path(key).is_file():
        return cert, key
    return None


def build_config() -> uvicorn.Config:
    pair = _certificate_pair()
    options: dict = {
        "host": _host(),
        "port": _port(),
        "proxy_headers": True,
        "forwarded_allow_ips": TRUSTED_FORWARDERS,
    }
    if pair:
        options["ssl_certfile"], options["ssl_keyfile"] = pair
    config = uvicorn.Config("app.main:app", **options)
    config.load()
    if config.ssl is not None:
        # Per-hostname contexts are built exactly like the default one, so a
        # certificate picked by SNI is served with the same TLS settings.
        def factory(certfile: str, keyfile: str):
            return create_ssl_context(
                certfile=certfile,
                keyfile=keyfile,
                password=config.ssl_keyfile_password,
                ssl_version=config.ssl_version,
                cert_reqs=config.ssl_cert_reqs,
                ca_certs=config.ssl_ca_certs,
                ciphers=config.ssl_ciphers,
            )

        panel_sni.install(config.ssl, factory)
    return config


def main() -> None:
    config = build_config()
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
