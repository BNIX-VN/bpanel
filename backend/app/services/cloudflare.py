"""Cloudflare API glue for DNS-01 wildcard certificates.

The panel only needs three things from Cloudflare: prove a token works, find
which zone a domain belongs to, and keep that token (encrypted) so certbot can
renew the wildcard unattended. The token is validated before it is stored and
never written to a log.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.secrets import decrypt, encrypt
from app.models.entities import CloudflareCredential

API_ROOT = "https://api.cloudflare.com/client/v4"
_TIMEOUT = 15


class CloudflareError(RuntimeError):
    """A Cloudflare API call failed or the token is not usable."""


def _get(path: str, token: str) -> dict:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "BPanel SSL",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise CloudflareError(f"Cloudflare API returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CloudflareError(f"Could not reach the Cloudflare API: {exc}") from exc
    except ValueError as exc:
        raise CloudflareError("Cloudflare API returned an unreadable response") from exc
    if not payload.get("success"):
        errors = payload.get("errors") or [{"message": "unknown error"}]
        raise CloudflareError(f"Cloudflare API error: {errors[0].get('message')}")
    return payload


def verify_token(token: str) -> dict:
    """Raise CloudflareError unless the token is live and DNS-capable."""
    if not (token or "").strip():
        raise CloudflareError("Cloudflare API token is empty")
    payload = _get("/user/tokens/verify", token)
    status = (payload.get("result") or {}).get("status")
    if status != "active":
        raise CloudflareError(f"Cloudflare token status is '{status}', expected 'active'")
    return payload["result"]


def list_zones(token: str) -> list[dict]:
    payload = _get("/zones?per_page=50", token)
    return payload.get("result") or []


def zone_for_domain(token: str, domain: str) -> str:
    """The longest zone name the token can see that is a suffix of ``domain``.

    For ``blog.shop.example.com`` with zones ``example.com`` and
    ``shop.example.com`` visible, this returns ``shop.example.com``.
    """
    name = (domain or "").strip().lower().rstrip(".")
    candidates = [
        (z.get("name") or "").lower()
        for z in list_zones(token)
        if (z.get("name") or "").lower()
        and (name == (z.get("name") or "").lower() or name.endswith("." + (z.get("name") or "").lower()))
    ]
    if not candidates:
        raise CloudflareError(
            f"No Cloudflare zone visible to this token covers {name}. "
            "Check the token's zone scope."
        )
    return max(candidates, key=len)


def get_token(db: Session, zone: str) -> str | None:
    row = db.query(CloudflareCredential).filter(CloudflareCredential.zone == zone.lower()).first()
    if not row:
        return None
    return decrypt(row.api_token)


def has_token(db: Session, zone: str) -> bool:
    return db.query(CloudflareCredential.id).filter(CloudflareCredential.zone == zone.lower()).first() is not None


def save_credential(db: Session, zone: str, token: str) -> None:
    zone = zone.lower()
    row = db.query(CloudflareCredential).filter(CloudflareCredential.zone == zone).first()
    if row:
        row.api_token = encrypt(token.strip())
        row.updated_at = datetime.utcnow()
    else:
        db.add(CloudflareCredential(zone=zone, api_token=encrypt(token.strip())))
    db.commit()
