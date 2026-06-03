import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings
from app.services.shell import shell


SETTINGS_DIR = Path(os.environ.get("BPANEL_DATA_DIR", "/var/lib/bpanel"))
SETTINGS_FILE = SETTINGS_DIR / "panel-settings.json"
ASSETS_DIR = SETTINGS_DIR / "assets"
MAX_ASSET_SIZE = 1024 * 1024
ALLOWED_ASSET_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "ico": "image/x-icon",
}
DOMAIN_RE = re.compile(r"^(?!-)([a-z0-9-]{1,63}\.)+[a-z]{2,}$")
IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def _read_raw() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _write_raw(data: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=str(SETTINGS_DIR), delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=True, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(SETTINGS_FILE)


def _asset_url(filename: str | None) -> str:
    if not filename:
        return ""
    path = ASSETS_DIR / filename
    if not path.exists():
        return ""
    version = int(path.stat().st_mtime)
    return f"/brand-assets/{filename}?v={version}"


def _is_ipv4(host: str) -> bool:
    if not IPV4_RE.fullmatch(host):
        return False
    return all(0 <= int(part) <= 255 for part in host.split("."))


def is_domain(host: str) -> bool:
    return bool(DOMAIN_RE.fullmatch((host or "").lower()))


def default_ssl_email(host: str) -> str:
    return f"admin@{host.lower()}" if is_domain(host) else ""


def normalize_panel_hostname(value: str) -> str:
    host = (value or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("Panel hostname is required")
    if "://" in host or "/" in host or ":" in host:
        raise ValueError("Panel hostname must not include a scheme, port, or path")
    if not is_domain(host) and not _is_ipv4(host) and host != "localhost":
        raise ValueError("Panel hostname must be a domain name or IPv4 address")
    return host


def normalize_panel_port(value: int | str | None) -> int:
    try:
        port = int(value or settings.panel_port or 2222)
    except (TypeError, ValueError) as exc:
        raise ValueError("Panel port is invalid") from exc
    if port < 1 or port > 65535:
        raise ValueError("Panel port is out of range")
    return port


def normalize_panel_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("Panel URL is required")
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Panel URL must start with http:// or https://")
    host = normalize_panel_hostname(host)
    port = normalize_panel_port(parsed.port or settings.panel_port or 2222)
    return f"{scheme}://{host}:{port}"


def panel_url_from_parts(hostname: str, port: int | str | None, scheme: str | None = None) -> str:
    safe_scheme = (scheme or "http").lower()
    if safe_scheme not in {"http", "https"}:
        raise ValueError("Panel URL scheme must be http or https")
    host = normalize_panel_hostname(hostname)
    safe_port = normalize_panel_port(port)
    return f"{safe_scheme}://{host}:{safe_port}"


def parse_panel_url(value: str) -> tuple[str, str, int]:
    normalized = normalize_panel_url(value)
    parsed = urlparse(normalized)
    return parsed.scheme, parsed.hostname or "", parsed.port or 2222


def has_panel_certificate() -> bool:
    cert_pairs = [
        (settings.panel_ssl_cert, settings.panel_ssl_key),
        ("/etc/bpanel/panel-fullchain.pem", "/etc/bpanel/panel-privkey.pem"),
    ]
    return any(bool(cert) and bool(key) and Path(cert).exists() and Path(key).exists() for cert, key in cert_pairs)


def current_settings() -> dict:
    data = _read_raw()
    app_name = (data.get("app_name") or settings.app_name or "BPanel").strip() or "BPanel"
    panel_url = data.get("panel_url") or settings.panel_url or ""
    panel_hostname = ""
    panel_port = settings.panel_port or 2222
    if panel_url:
        try:
            _scheme, panel_hostname, panel_port = parse_panel_url(panel_url)
        except ValueError:
            panel_hostname = ""
            panel_port = settings.panel_port or 2222
    ssl_enabled = panel_url.startswith("https://") and has_panel_certificate()
    return {
        "app_name": app_name,
        "panel_url": panel_url,
        "panel_hostname": panel_hostname,
        "panel_port": panel_port,
        "logo_url": _asset_url(data.get("logo_filename")),
        "favicon_url": _asset_url(data.get("favicon_filename")) or "/favicon.png",
        "ssl_enabled": ssl_enabled,
    }


def update_settings(
    app_name: str | None = None,
    panel_hostname: str | None = None,
    panel_port: int | None = None,
    panel_url: str | None = None,
) -> dict:
    del panel_port  # The panel port is install-time only; settings can change hostname/branding.
    data = _read_raw()
    if app_name is not None:
        value = app_name.strip()
        if not 2 <= len(value) <= 80:
            raise ValueError("Panel name must be 2-80 characters")
        data["app_name"] = value
    if (panel_hostname is not None and panel_hostname.strip()) or (panel_url is not None and panel_url.strip()):
        existing_url = data.get("panel_url") or settings.panel_url or ""
        existing_normalized = normalize_panel_url(existing_url) if existing_url else ""
        existing_scheme, existing_host, existing_port = parse_panel_url(existing_normalized) if existing_normalized else ("http", "", settings.panel_port or 2222)
        if panel_hostname is not None and panel_hostname.strip():
            normalized = panel_url_from_parts(panel_hostname, existing_port, existing_scheme)
        elif panel_url is not None and panel_url.strip():
            requested_scheme, requested_host, _requested_port = parse_panel_url(panel_url)
            normalized = panel_url_from_parts(requested_host, existing_port, requested_scheme)
        else:
            normalized = existing_normalized
        if not normalized:
            raise ValueError("Panel hostname is required")
        scheme, host, port = parse_panel_url(normalized)
        if scheme == "https" and not has_panel_certificate():
            raise ValueError("Use Install SSL before saving an HTTPS panel URL")
        if normalized != existing_normalized:
            result = shell.privileged(
                "panel-url-set",
                helper_args=[scheme, host, str(port)],
                check=False,
                fallback=["bash", "-lc", "true"],
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "Could not update panel URL").strip())
        data["panel_url"] = normalized
    _write_raw(data)
    return current_settings()


def detect_asset_type(content: bytes, filename: str) -> tuple[str, str]:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    if content.startswith(b"\x00\x00\x01\x00"):
        return "ico", "image/x-icon"
    if suffix in ALLOWED_ASSET_TYPES:
        raise ValueError("Uploaded file content does not match its image type")
    raise ValueError("Only PNG, JPG, WEBP, and ICO images are supported")


async def save_asset(kind: str, upload: UploadFile) -> dict:
    if kind not in {"logo", "favicon"}:
        raise ValueError("Invalid asset kind")
    content = await upload.read(MAX_ASSET_SIZE + 1)
    if len(content) > MAX_ASSET_SIZE:
        raise ValueError("Image must be 1 MB or smaller")
    ext, _media_type = detect_asset_type(content, upload.filename or "")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    data = _read_raw()
    previous = data.get(f"{kind}_filename")
    if previous:
        try:
            (ASSETS_DIR / previous).unlink()
        except OSError:
            pass
    filename = f"{kind}.{ext}"
    (ASSETS_DIR / filename).write_bytes(content)
    data[f"{kind}_filename"] = filename
    _write_raw(data)
    return current_settings()


def asset_path(filename: str) -> tuple[Path, str]:
    if not re.fullmatch(r"(?:logo|favicon)\.(?:png|jpg|jpeg|webp|ico)", filename or ""):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    path = ASSETS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    media_type = ALLOWED_ASSET_TYPES.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    return path, media_type


def install_panel_ssl(email: str | None = None, panel_hostname: str | None = None, panel_port: int | None = None, panel_url: str | None = None) -> dict:
    if panel_hostname:
        normalized = panel_url_from_parts(panel_hostname, panel_port, "http")
    elif panel_url:
        normalized = normalize_panel_url(panel_url)
    else:
        raise ValueError("Panel hostname is required")
    _scheme, host, port = parse_panel_url(normalized)
    if not is_domain(host):
        raise ValueError("Panel SSL requires a domain name, not an IP address")
    certbot_email = (email or settings.ssl_email or default_ssl_email(host)).strip()
    helper_args = [host, str(port)]
    if certbot_email:
        helper_args.append(certbot_email)
    result = shell.privileged(
        "panel-ssl-install",
        helper_args=helper_args,
        check=False,
        fallback=["bash", "-lc", "true"],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Could not install panel SSL").strip())
    data = _read_raw()
    data["panel_url"] = f"https://{host}:{port}"
    _write_raw(data)
    current = current_settings()
    current["message"] = result.stdout.strip() or f"Panel SSL enabled for {host}"
    return current
