"""A panel certificate that cannot be used no longer means plain HTTP (1.20.3).

serve.py used to start uvicorn without TLS whenever the configured certificate
file was missing, so the whole panel - login form and session cookie included -
went over the network in clear text. Now: the configured certificate, else the
self-signed one, else a recovery page with no application behind it. An
http:// panel URL, which the administrator sets on purpose, is still served.
"""
import asyncio
import datetime
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app import serve
from app.core import tls_degraded


def _pair(directory: Path, name: str) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / f"{name}-fullchain.pem", directory / f"{name}-privkey.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    return str(cert_path), str(key_path)


@pytest.fixture
def certs(tmp_path, monkeypatch):
    configured = _pair(tmp_path, "panel")
    fallback = _pair(tmp_path, "selfsigned")
    monkeypatch.setattr(serve, "SELF_SIGNED_PAIR", fallback)

    def configure(cert, key):
        monkeypatch.setenv("PANEL_SSL_CERT", cert)
        monkeypatch.setenv("PANEL_SSL_KEY", key)

    return configured, fallback, configure, tmp_path


def test_the_configured_certificate_is_used(certs):
    configured, _fallback, configure, _tmp = certs
    configure(*configured)
    assert serve.choose_tls() == ("https", configured)


def test_a_missing_certificate_falls_back_to_the_self_signed_one(certs):
    _configured, fallback, configure, tmp = certs
    configure(str(tmp / "gone-fullchain.pem"), str(tmp / "gone-privkey.pem"))
    assert serve.choose_tls() == ("https", fallback)


def test_a_key_that_is_not_the_certificates_falls_back_too(certs):
    configured, fallback, configure, _tmp = certs
    configure(configured[0], fallback[1])
    assert serve.choose_tls() == ("https", fallback)


def test_a_corrupt_certificate_falls_back_too(certs):
    configured, fallback, configure, tmp = certs
    broken = tmp / "broken.pem"
    broken.write_text("-----BEGIN CERTIFICATE-----\nnot base64\n-----END CERTIFICATE-----\n")
    configure(str(broken), configured[1])
    assert serve.choose_tls() == ("https", fallback)


def test_with_nothing_usable_the_port_serves_only_the_recovery_page(certs, monkeypatch):
    _configured, _fallback, configure, tmp = certs
    configure(str(tmp / "gone-fullchain.pem"), str(tmp / "gone-privkey.pem"))
    monkeypatch.setattr(serve, "SELF_SIGNED_PAIR", (str(tmp / "no.pem"), str(tmp / "no-key.pem")))
    assert serve.choose_tls() == ("degraded", None)
    config = serve.build_config()
    # Not the panel: the recovery page, and nothing else, over plain HTTP.
    assert config.app == "app.core.tls_degraded:app"
    assert config.ssl is None


def test_an_http_panel_url_is_still_served_over_http(monkeypatch):
    # `panel-url-set http ...` empties both values: the administrator's choice.
    monkeypatch.setenv("PANEL_SSL_CERT", "")
    monkeypatch.setenv("PANEL_SSL_KEY", "")
    assert serve.choose_tls() == ("http", None)


def test_half_a_configuration_is_not_taken_for_http(certs, monkeypatch):
    # A certificate with its key line lost is a broken TLS setup, not a
    # request for plain HTTP.
    configured, fallback, _configure, _tmp = certs
    monkeypatch.setenv("PANEL_SSL_CERT", configured[0])
    monkeypatch.setenv("PANEL_SSL_KEY", "")
    assert serve.choose_tls() == ("https", fallback)


def _call(path="/"):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": path, "headers": []}
    asyncio.run(tls_degraded.app(scope, receive, send))
    return sent


@pytest.mark.parametrize("path", ["/", "/api/auth/login", "/api/health"])
def test_every_request_gets_the_same_503_and_no_cookie(path):
    start, body = _call(path)
    assert start["status"] == 503
    headers = dict(start["headers"])
    assert b"set-cookie" not in headers and headers[b"cache-control"] == b"no-store"
    page = body["body"].decode("utf-8")
    assert "bpanel install-panel-ssl" in page and "journalctl -u bpanel-api" in page
    assert "panel-ssl-selfsigned" in page and "<form" not in page


def test_the_recovery_page_imports_nothing_of_the_panel():
    source = Path(tls_degraded.__file__).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert imports == ["from __future__ import annotations"]
