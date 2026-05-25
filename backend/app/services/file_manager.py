import os
import shutil
from pathlib import Path
from typing import Dict, List

from app.models.entities import Website
from app.services import site_users


MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
BLOCKED_WRITE_SUFFIXES = {
    ".php", ".phtml", ".phar", ".pht", ".php3", ".php4", ".php5", ".php7", ".php8",
    ".cgi", ".pl", ".py", ".sh", ".exe", ".dll", ".so",
    ".htaccess", ".htpasswd",
}
# Filenames that bypass suffix rules (no extension) but are still dangerous.
BLOCKED_WRITE_NAMES = {".user.ini", ".env", ".htaccess", ".htpasswd", "wp-config.php"}
SENSITIVE_READ_NAMES = {".user.ini", ".env", "wp-config.php", ".htpasswd"}


def _safe_upload_name(filename: str) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise ValueError("Invalid filename")
    return name


def _safe_path(website: Website, relative_path: str) -> Path:
    """Resolve a relative path under the website root and reject anything that
    escapes via .., absolute paths, or symlinks.
    """
    if "\x00" in (relative_path or ""):
        raise ValueError("Invalid path")
    root = Path(website.root_path).resolve()
    if not root.exists():
        raise ValueError("Website root not found")
    # Strip leading slashes and disallow absolute paths
    rel = (relative_path or "").lstrip("/").lstrip("\\")
    candidate = root / rel
    # Walk each component and reject symlinks anywhere along the way.
    accumulated = root
    if candidate != root:
        try:
            parts = candidate.relative_to(root).parts
        except ValueError:
            # candidate is not under root (e.g. via .. before resolve)
            parts = None
        if parts is None:
            # Fallback: resolve and verify containment.
            resolved = candidate.resolve()
            if root != resolved and root not in resolved.parents:
                raise ValueError("Path escapes website root")
            return resolved
        for part in parts:
            if part in ("..", "."):
                raise ValueError("Path escapes website root")
            accumulated = accumulated / part
            if accumulated.is_symlink():
                raise ValueError("Symlinks are not allowed")
    target = accumulated.resolve()
    if root != target and root not in target.parents:
        raise ValueError("Path escapes website root")
    return target


def list_files(website: Website, relative_path: str = "") -> List[Dict]:
    target = _safe_path(website, relative_path)
    if not target.exists() or not target.is_dir():
        return []
    items = []
    for item in target.iterdir():
        # Hide symlinks rather than following them.
        if item.is_symlink():
            continue
        try:
            rel = str(item.relative_to(Path(website.root_path)))
        except ValueError:
            continue
        items.append({
            "name": item.name,
            "path": rel,
            "is_dir": item.is_dir(),
            "size": item.stat().st_size,
        })
    return items


def read_text_file(website: Website, relative_path: str, allow_sensitive: bool = False) -> str:
    target = _safe_path(website, relative_path)
    if not target.is_file():
        raise ValueError("File not found")
    if target.is_symlink():
        raise ValueError("Symlinks are not allowed")
    if target.name.lower() in SENSITIVE_READ_NAMES and not allow_sensitive:
        raise ValueError(f"Reading {target.name} requires admin permissions")
    if target.stat().st_size > MAX_TEXT_FILE_BYTES:
        raise ValueError("File is too large")
    return target.read_text(encoding="utf-8")


def write_text_file(website: Website, relative_path: str, content: str, allow_executable: bool = False) -> str:
    target = _safe_path(website, relative_path)
    name_lower = target.name.lower()
    if name_lower in BLOCKED_WRITE_NAMES and not allow_executable:
        raise ValueError(f"Writing {target.name} requires admin permissions")
    if target.suffix.lower() in BLOCKED_WRITE_SUFFIXES and not allow_executable:
        raise ValueError("Writing executable files requires admin permissions")
    if len(content.encode("utf-8")) > MAX_TEXT_FILE_BYTES:
        raise ValueError("File content is too large")
    if target.exists() and target.is_symlink():
        raise ValueError("Refusing to write through a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    site_users.fix_site_path(str(target.parent), website.linux_user)
    return str(target)


def upload_file(website: Website, directory_path: str, filename: str, source_file, allow_executable: bool = False) -> str:
    target_dir = _safe_path(website, directory_path or "public")
    if target_dir.exists() and not target_dir.is_dir():
        raise ValueError("Upload target is not a directory")
    if target_dir.is_symlink():
        raise ValueError("Symlinks are not allowed")
    safe_name = _safe_upload_name(filename)
    target = target_dir / safe_name
    if target.exists() and target.is_symlink():
        raise ValueError("Refusing to overwrite a symlink")
    name_lower = safe_name.lower()
    if name_lower in BLOCKED_WRITE_NAMES and not allow_executable:
        raise ValueError(f"Uploading {safe_name} requires admin permissions")
    if target.suffix.lower() in BLOCKED_WRITE_SUFFIXES and not allow_executable:
        raise ValueError("Uploading executable files requires admin permissions")
    target_dir.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        shutil.copyfileobj(source_file, output, length=1024 * 1024)
    site_users.fix_site_path(str(target), website.linux_user)
    return str(target)


def delete_file(website: Website, relative_path: str, allow_executable: bool = False) -> str:
    target = _safe_path(website, relative_path)
    if target.is_dir():
        raise ValueError("Cannot delete directory")
    name_lower = target.name.lower()
    if name_lower in BLOCKED_WRITE_NAMES and not allow_executable:
        raise ValueError(f"Deleting {target.name} requires admin permissions")
    if target.suffix.lower() in BLOCKED_WRITE_SUFFIXES and not allow_executable:
        raise ValueError("Deleting executable files requires admin permissions")
    target.unlink(missing_ok=True)
    return str(target)
