import os
import secrets
import shutil
import stat
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from app.models.entities import Website
from app.services import site_users
from app.services import storage_quota
from app.services.shell import shell


def _env_int(name: str, default: int) -> Optional[int]:
    """Parse an integer environment variable.

    Returns None if the variable is not set or set to empty string,
    otherwise returns the parsed integer (clamped to >= 0).
    Use None return value to distinguish "not set" from "set to 0".
    """
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_ITEMS = _env_int("BPANEL_MAX_ARCHIVE_ITEMS", 1_000_000)
MAX_ARCHIVE_UNCOMPRESSED_BYTES = _env_int("BPANEL_MAX_ARCHIVE_UNCOMPRESSED_BYTES", 100 * 1024 * 1024 * 1024)
# Website ownership is the permission boundary. End users must be able to deploy
# real web sources, including PHP, .htaccess, .env, and wp-config.php.
BLOCKED_WRITE_SUFFIXES: set[str] = set()
BLOCKED_WRITE_NAMES: set[str] = set()
SENSITIVE_READ_NAMES: set[str] = set()


def _safe_upload_name(filename: str) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise ValueError("Invalid filename")
    return name


def _safe_entry_name(name: str) -> str:
    safe_name = _safe_upload_name(name)
    if safe_name in {"/", "\\"}:
        raise ValueError("Invalid filename")
    return safe_name


def _assert_write_allowed(path: Path, action: str, allow_executable: bool = False) -> None:
    if allow_executable:
        return
    name_lower = path.name.lower()
    if name_lower in BLOCKED_WRITE_NAMES:
        raise ValueError(f"{action} {path.name} requires admin permissions")
    if path.suffix.lower() in BLOCKED_WRITE_SUFFIXES:
        raise ValueError(f"{action} executable files requires admin permissions")


def _assert_sensitive_read_allowed(path: Path, action: str, allow_sensitive: bool = False) -> None:
    if allow_sensitive:
        return
    if path.name.lower() in SENSITIVE_READ_NAMES:
        raise ValueError(f"{action} {path.name} requires admin permissions")


def _assert_tree_write_allowed(path: Path, action: str, allow_executable: bool = False) -> None:
    if path.is_symlink():
        raise ValueError("Symlinks are not allowed")
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_symlink():
                raise ValueError("Symlinks are not allowed")
            if item.is_file():
                _assert_write_allowed(item, action, allow_executable)
        return
    _assert_write_allowed(path, action, allow_executable)


def _assert_tree_read_allowed(path: Path, action: str, allow_sensitive: bool = False) -> None:
    if path.is_symlink():
        raise ValueError("Symlinks are not allowed")
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_symlink():
                raise ValueError("Symlinks are not allowed")
            if item.is_file():
                _assert_sensitive_read_allowed(item, action, allow_sensitive)
        return
    _assert_sensitive_read_allowed(path, action, allow_sensitive)


def _clean_relative_path(path: str) -> str:
    if "\x00" in (path or ""):
        raise ValueError("Invalid path")
    normalized = (path or "").replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/", 1)[0]:
        raise ValueError("Path escapes website root")
    parts = []
    for part in normalized.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("Path escapes website root")
        parts.append(part)
    return "/".join(parts)


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


def _relative_to_root(website: Website, path: Path) -> str:
    return str(path.relative_to(Path(website.root_path).resolve())).replace("\\", "/")


def _entry_info(website: Website, item: Path) -> Dict:
    item_stat = item.stat()
    return {
        "name": item.name,
        "path": _relative_to_root(website, item),
        "is_dir": item.is_dir(),
        "size": item_stat.st_size,
        "modified": int(item_stat.st_mtime),
        "mode": f"{stat.S_IMODE(item_stat.st_mode):03o}",
    }


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
            items.append(_entry_info(website, item))
        except (OSError, ValueError):
            continue
    return sorted(items, key=lambda entry: (not entry["is_dir"], entry["name"].lower()))


def make_directory(website: Website, parent_path: str, name: str) -> str:
    parent = _safe_path(website, parent_path or site_users.PUBLIC_DIR)
    if not parent.exists() or not parent.is_dir():
        raise ValueError("Parent directory not found")
    target = parent / _safe_entry_name(name)
    if target.exists():
        raise ValueError("File or folder already exists")
    target.mkdir()
    site_users.fix_site_path(str(target), website.linux_user)
    return str(target)


def rename_entry(website: Website, relative_path: str, new_name: str, allow_executable: bool = False) -> str:
    source = _safe_path(website, relative_path)
    if not source.exists():
        raise ValueError("File or folder not found")
    if source == Path(website.root_path).resolve():
        raise ValueError("Cannot rename website root")
    target = source.parent / _safe_entry_name(new_name)
    if target.exists():
        raise ValueError("Target already exists")
    _assert_tree_write_allowed(source, "Renaming", allow_executable)
    _assert_write_allowed(target, "Renaming", allow_executable)
    source.rename(target)
    site_users.fix_site_path(str(target), website.linux_user)
    return str(target)


def chmod_entry(website: Website, relative_path: str, mode: str) -> str:
    target = _safe_path(website, relative_path)
    if not target.exists():
        raise ValueError("File or folder not found")
    if target.is_symlink():
        raise ValueError("Symlinks are not allowed")
    clean_mode = (mode or "").strip()
    if len(clean_mode) not in {3, 4} or any(char not in "01234567" for char in clean_mode):
        raise ValueError("Mode must be octal, for example 644 or 755")
    numeric_mode = int(clean_mode, 8)
    if numeric_mode > 0o7777:
        raise ValueError("Mode is out of range")
    # Enforce sensible defaults: files=644, dirs=755. Block world-writable and dangerous modes.
    is_dir = target.is_dir()
    if is_dir:
        # Directory: owner rwx (7), group r-x (5), other r-x (5)
        valid_modes = {0o755, 0o750, 0o700, 0o775, 0o770}
    else:
        # File: owner rw- (6), group r-- (4), other r-- (4)
        valid_modes = {0o644, 0o640, 0o600, 0o664, 0o660}
    if numeric_mode not in valid_modes:
        default = "755" if is_dir else "644"
        raise ValueError(f"Mode must be one of: {', '.join(oct(m)[2:] for m in sorted(valid_modes))}. Suggested: {default}")
    if website.linux_user:
        root = Path(website.root_path).resolve()
        relative = str(target.relative_to(root)).replace("\\", "/") if target != root else "."
        shell.privileged(
            "terminal-exec",
            helper_args=[website.linux_user, str(root), "chmod", clean_mode, relative],
            fallback=["chmod", clean_mode, str(target)],
        )
        return str(target)
    target.chmod(numeric_mode)
    return str(target)


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
    if website.linux_user:
        root = Path(website.root_path).resolve()
        result = shell.privileged(
            "terminal-exec",
            helper_args=[website.linux_user, str(root), "cat", _helper_relative_path(website, target)],
            fallback=["cat", str(target)],
        )
        return result.stdout
    return target.read_text(encoding="utf-8")


QuotaCheck = Callable[[int, int], None]


def _existing_file_size(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _helper_relative_path(website: Website, target: Path) -> str:
    root = Path(website.root_path).resolve()
    return str(target.relative_to(root)).replace("\\", "/") if target != root else "."


def _write_text_as_site_user(website: Website, target: Path, content: str) -> None:
    if not website.linux_user:
        target.write_text(content, encoding="utf-8")
        return
    root = Path(website.root_path).resolve()
    try:
        shell.privileged(
            "site-file-write",
            helper_args=[website.linux_user, str(root), _helper_relative_path(website, target)],
            input=content,
        )
    except RuntimeError:
        # Fallback for dev/test environments without bpanel-helper installed
        target.write_text(content, encoding="utf-8")


def create_text_file(
    website: Website,
    parent_path: str,
    name: str,
    allow_executable: bool = False,
    quota_check: Optional[QuotaCheck] = None,
) -> str:
    parent = _safe_path(website, parent_path or "")
    if parent.exists() and not parent.is_dir():
        raise ValueError("Parent path is not a directory")
    if parent.is_symlink():
        raise ValueError("Symlinks are not allowed")
    target = parent / _safe_entry_name(name)
    if target.exists():
        raise ValueError("File or folder already exists")
    _assert_write_allowed(target, "Creating", allow_executable)
    if quota_check:
        quota_check(0, 0)
    if website.linux_user:
        _write_text_as_site_user(website, target, "")
    else:
        parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    return str(target)


def write_text_file(
    website: Website,
    relative_path: str,
    content: str,
    allow_executable: bool = False,
    quota_check: Optional[QuotaCheck] = None,
) -> str:
    target = _safe_path(website, relative_path)
    _assert_write_allowed(target, "Writing", allow_executable)
    content_size = len(content.encode("utf-8"))
    if content_size > MAX_TEXT_FILE_BYTES:
        raise ValueError("File content is too large")
    if target.exists() and target.is_symlink():
        raise ValueError("Refusing to write through a symlink")
    if quota_check:
        quota_check(content_size, _existing_file_size(target))
    _write_text_as_site_user(website, target, content)
    if not website.linux_user:
        site_users.fix_site_path(str(target.parent), website.linux_user)
    return str(target)


def upload_file(
    website: Website,
    directory_path: str,
    filename: str,
    source_file,
    allow_executable: bool = False,
    quota_check: Optional[QuotaCheck] = None,
) -> str:
    target_dir = _safe_path(website, directory_path or site_users.PUBLIC_DIR)
    if target_dir.exists() and not target_dir.is_dir():
        raise ValueError("Upload target is not a directory")
    if target_dir.is_symlink():
        raise ValueError("Symlinks are not allowed")
    safe_name = _safe_upload_name(filename)
    target = target_dir / safe_name
    if target.exists() and target.is_symlink():
        raise ValueError("Refusing to overwrite a symlink")
    _assert_write_allowed(target, "Uploading", allow_executable)
    if quota_check:
        upload_size = storage_quota.source_file_size(source_file)
        quota_check(upload_size or 0, _existing_file_size(target))
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path = target_dir / f".{safe_name}.upload-{secrets.token_hex(8)}.tmp"
    try:
        with temp_path.open("wb") as output:
            shutil.copyfileobj(source_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        temp_path.replace(target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    site_users.fix_site_path(str(target), website.linux_user)
    return str(target)


def delete_file(website: Website, relative_path: str, allow_executable: bool = False) -> str:
    target = _safe_path(website, relative_path)
    if target.is_dir():
        raise ValueError("Cannot delete directory")
    _assert_write_allowed(target, "Deleting", allow_executable)
    target.unlink(missing_ok=True)
    return str(target)


def delete_entries(website: Website, paths: Iterable[str], allow_executable: bool = False) -> List[str]:
    deleted = []
    root = Path(website.root_path).resolve()
    targets = []
    for relative_path in paths:
        target = _safe_path(website, relative_path)
        if not target.exists():
            raise ValueError("File or folder not found")
        if target == root:
            raise ValueError("Cannot delete website root")
        if target.is_symlink():
            raise ValueError("Symlinks are not allowed")
        _assert_tree_write_allowed(target, "Deleting", allow_executable)
        targets.append(target)

    deleted_dirs = []
    for target in targets:
        if any(parent in target.parents for parent in deleted_dirs):
            continue
        if target.is_dir():
            shutil.rmtree(target)
            deleted_dirs.append(target)
        else:
            target.unlink(missing_ok=True)
        deleted.append(str(target))
    return deleted


def _transfer_sources(website: Website, paths: Iterable[str], action: str, allow_executable: bool, allow_sensitive: bool) -> list[Path]:
    root = Path(website.root_path).resolve()
    sources = []
    for relative_path in paths:
        source = _safe_path(website, relative_path)
        if not source.exists():
            raise ValueError("File or folder not found")
        if source == root:
            raise ValueError(f"Cannot {action.lower()} website root")
        if source.is_symlink():
            raise ValueError("Symlinks are not allowed")
        if action == "Copying":
            _assert_tree_read_allowed(source, action, allow_sensitive)
            _assert_tree_write_allowed(source, action, allow_executable)
        else:
            _assert_tree_write_allowed(source, action, allow_executable)
        sources.append(source)
    if not sources:
        raise ValueError("Select files or folders first")

    top_level = []
    for source in sorted(dict.fromkeys(sources), key=lambda item: len(item.parts)):
        if any(parent.is_dir() and parent in source.parents for parent in top_level):
            continue
        top_level.append(source)
    return top_level


def _transfer_destination(website: Website, destination_path: str) -> Path:
    destination = _safe_path(website, destination_path or site_users.PUBLIC_DIR)
    if not destination.exists() or not destination.is_dir():
        raise ValueError("Destination folder not found")
    if destination.is_symlink():
        raise ValueError("Symlinks are not allowed")
    return destination


def _assert_transfer_target(source: Path, destination: Path, target: Path, action: str) -> None:
    if source.is_dir() and (destination == source or source in destination.parents):
        raise ValueError(f"Cannot {action.lower()} a folder into itself")
    if target.exists() or target.is_symlink():
        raise ValueError(f"Target already exists: {target.name}")


def copy_entries(
    website: Website,
    paths: Iterable[str],
    destination_path: str,
    allow_executable: bool = False,
    allow_sensitive: bool = False,
    quota_check: Optional[QuotaCheck] = None,
) -> List[str]:
    sources = _transfer_sources(website, paths, "Copying", allow_executable, allow_sensitive)
    destination = _transfer_destination(website, destination_path)
    targets = [destination / source.name for source in sources]
    for source, target in zip(sources, targets):
        _assert_transfer_target(source, destination, target, "copy")
        _assert_write_allowed(target, "Copying", allow_executable)
    if quota_check:
        quota_check(_total_size(sources), 0)

    copied = []
    for source, target in zip(sources, targets):
        if source.is_dir():
            shutil.copytree(source, target, copy_function=shutil.copy2)
        else:
            shutil.copy2(source, target)
        site_users.fix_site_path(str(target), website.linux_user)
        copied.append(str(target))
    return copied


def move_entries(
    website: Website,
    paths: Iterable[str],
    destination_path: str,
    allow_executable: bool = False,
    allow_sensitive: bool = False,
) -> List[str]:
    sources = _transfer_sources(website, paths, "Moving", allow_executable, allow_sensitive)
    destination = _transfer_destination(website, destination_path)
    targets = [destination / source.name for source in sources]
    for source, target in zip(sources, targets):
        _assert_transfer_target(source, destination, target, "move")
        _assert_write_allowed(target, "Moving", allow_executable)

    moved = []
    for source, target in zip(sources, targets):
        shutil.move(str(source), str(target))
        site_users.fix_site_path(str(target), website.linux_user)
        moved.append(str(target))
    return moved


def _total_size(paths: Iterable[Path]) -> int:
    total = 0
    for path in paths:
        if path.is_dir():
            total += storage_quota.path_usage_bytes(path)
        elif path.is_file():
            total += path.stat().st_size
    return total


def _archive_output_name(output_name: str, archive_format: str) -> str:
    name = _safe_entry_name(output_name or f"archive-{int(time.time())}")
    if archive_format == "zip":
        return name if name.lower().endswith(".zip") else f"{name}.zip"
    if archive_format == "tar.gz":
        return name if name.lower().endswith(".tar.gz") else f"{name}.tar.gz"
    raise ValueError("Unsupported archive format")


def _archive_arcname(base: Path, path: Path) -> str:
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise ValueError("Archive items must be inside the current folder") from exc
    arcname = str(relative).replace("\\", "/")
    if not arcname:
        raise ValueError("Cannot archive the current folder into itself")
    return arcname


def archive_entries(
    website: Website,
    base_path: str,
    paths: Iterable[str],
    output_name: str,
    archive_format: str = "zip",
    allow_sensitive: bool = False,
    quota_check: Optional[QuotaCheck] = None,
) -> str:
    base = _safe_path(website, base_path or site_users.PUBLIC_DIR)
    if not base.exists() or not base.is_dir():
        raise ValueError("Archive directory not found")
    selected = [_safe_path(website, path) for path in paths]
    if not selected:
        raise ValueError("Select files or folders to archive")
    for path in selected:
        if not path.exists():
            raise ValueError("File or folder not found")
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed")
        _assert_tree_read_allowed(path, "Archiving", allow_sensitive)
        _archive_arcname(base, path)
    output_path = base / _archive_output_name(output_name, archive_format)
    if output_path.exists():
        raise ValueError("Archive output already exists")
    for path in selected:
        if path == output_path or (path.is_dir() and path in output_path.parents):
            raise ValueError("Archive output cannot be inside a selected folder")
    if quota_check:
        quota_check(_total_size(selected), 0)
    if archive_format == "zip":
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in selected:
                if path.is_dir():
                    archive.writestr(f"{_archive_arcname(base, path).rstrip('/')}/", b"")
                    for item in path.rglob("*"):
                        if item.is_symlink():
                            continue
                        if item.is_dir():
                            archive.writestr(f"{_archive_arcname(base, item).rstrip('/')}/", b"")
                            continue
                        if item.is_file():
                            archive.write(item, arcname=_archive_arcname(base, item))
                elif path.is_file():
                    archive.write(path, arcname=_archive_arcname(base, path))
    else:
        with tarfile.open(output_path, "w:gz") as archive:
            for path in selected:
                archive.add(
                    path,
                    arcname=_archive_arcname(base, path),
                    recursive=True,
                    filter=lambda member: None if (member.issym() or member.islnk() or member.isdev()) else member,
                )
    site_users.fix_site_path(str(output_path), website.linux_user)
    return str(output_path)


def _validate_archive_destination(base: Path, member_name: str) -> Path:
    clean = _clean_relative_path(member_name)
    if not clean:
        raise ValueError("Invalid archive member path")
    target = (base / clean).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Archive contains unsafe paths")
    return target


def _is_source_archive_target(target: Path, archive_file: Path) -> bool:
    return target.resolve() == archive_file.resolve()


def _zip_uncompressed_size(
    archive: zipfile.ZipFile,
    destination: Path,
    archive_file: Path,
    allow_executable: bool = False,
) -> int:
    total = 0
    for index, info in enumerate(archive.infolist(), start=1):
        if MAX_ARCHIVE_ITEMS is not None and index > MAX_ARCHIVE_ITEMS:
            raise ValueError(f"Archive has too many files (limit {MAX_ARCHIVE_ITEMS})")
        mode = (info.external_attr >> 16) & 0o170000
        if stat.S_ISLNK(mode):
            raise ValueError("Archive symlinks are not allowed")
        target = _validate_archive_destination(destination, info.filename)
        if _is_source_archive_target(target, archive_file):
            continue
        if target.exists() and target.is_symlink():
            raise ValueError("Refusing to overwrite a symlink")
        if info.is_dir():
            if target.exists() and not target.is_dir():
                raise ValueError("Archive directory conflicts with an existing file")
            continue
        if target.exists() and target.is_dir():
            raise ValueError("Archive file conflicts with an existing directory")
        _assert_write_allowed(target, "Extracting", allow_executable)
        total += info.file_size
        if MAX_ARCHIVE_UNCOMPRESSED_BYTES is not None and total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("Archive is too large")
    return total


def _tar_uncompressed_size(
    archive: tarfile.TarFile,
    destination: Path,
    archive_file: Path,
    allow_executable: bool = False,
) -> int:
    total = 0
    for index, member in enumerate(archive, start=1):
        if MAX_ARCHIVE_ITEMS is not None and index > MAX_ARCHIVE_ITEMS:
            raise ValueError(f"Archive has too many files (limit {MAX_ARCHIVE_ITEMS})")
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError("Archive links and devices are not allowed")
        target = _validate_archive_destination(destination, member.name)
        if _is_source_archive_target(target, archive_file):
            continue
        if target.exists() and target.is_symlink():
            raise ValueError("Refusing to overwrite a symlink")
        if member.isdir():
            if target.exists() and not target.is_dir():
                raise ValueError("Archive directory conflicts with an existing file")
            continue
        if not member.isfile():
            raise ValueError("Archive contains unsupported entries")
        if target.exists() and target.is_dir():
            raise ValueError("Archive file conflicts with an existing directory")
        _assert_write_allowed(target, "Extracting", allow_executable)
        total += member.size
        if MAX_ARCHIVE_UNCOMPRESSED_BYTES is not None and total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("Archive is too large")
    return total


def _extract_zip_archive(archive: zipfile.ZipFile, destination: Path, archive_file: Path) -> None:
    for info in archive.infolist():
        target = _validate_archive_destination(destination, info.filename)
        if _is_source_archive_target(target, archive_file):
            continue
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        except RuntimeError as exc:
            raise ValueError("Archive entry cannot be extracted") from exc


def _extract_tar_archive(archive: tarfile.TarFile, destination: Path, archive_file: Path) -> None:
    for member in archive:
        target = _validate_archive_destination(destination, member.name)
        if _is_source_archive_target(target, archive_file):
            continue
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        source = archive.extractfile(member)
        if source is None:
            raise ValueError("Archive entry cannot be extracted")
        target.parent.mkdir(parents=True, exist_ok=True)
        with source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def extract_archive(
    website: Website,
    archive_path: str,
    destination_path: str = "",
    allow_executable: bool = False,
    quota_check: Optional[QuotaCheck] = None,
) -> str:
    archive_file = _safe_path(website, archive_path)
    if not archive_file.exists() or not archive_file.is_file():
        raise ValueError("Archive not found")
    if archive_file.is_symlink():
        raise ValueError("Symlinks are not allowed")
    destination = _safe_path(website, destination_path or str(Path(archive_path).parent))
    if not destination.exists() or not destination.is_dir():
        raise ValueError("Extract destination not found")

    suffix = archive_file.name.lower()
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(archive_file) as archive:
            incoming = _zip_uncompressed_size(archive, destination, archive_file, allow_executable)
            if quota_check:
                quota_check(incoming, 0)
            _extract_zip_archive(archive, destination, archive_file)
    elif suffix.endswith(".tar.gz") or suffix.endswith(".tgz"):
        with tarfile.open(archive_file, "r:gz") as archive:
            incoming = _tar_uncompressed_size(archive, destination, archive_file, allow_executable)
            if quota_check:
                quota_check(incoming, 0)
            _extract_tar_archive(archive, destination, archive_file)
    else:
        raise ValueError("Only .zip, .tar.gz, and .tgz archives can be extracted")
    site_users.fix_site_path(str(destination), website.linux_user)
    return str(destination)


def download_file_path(website: Website, relative_path: str, allow_sensitive: bool = False) -> Path:
    target = _safe_path(website, relative_path)
    if not target.exists() or not target.is_file():
        raise ValueError("File not found")
    if target.is_symlink():
        raise ValueError("Symlinks are not allowed")
    _assert_sensitive_read_allowed(target, "Downloading", allow_sensitive)
    return target
