from datetime import datetime
from pathlib import Path
from typing import List, Optional
import shutil
import tarfile

from app.core.config import settings
from app.models.entities import Website
from app.services.mariadb import export_database
from app.services.shell import shell


MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


def create_backup(website: Website, db_name: Optional[str] = None) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    backup_dir = Path(settings.backup_root) / website.domain
    archive = backup_dir / f"{website.domain}-{stamp}.tar.gz"
    sql_file = backup_dir / f"{website.domain}-{stamp}.sql"
    shell.run(["mkdir", "-p", str(backup_dir)])
    backup_dir.mkdir(parents=True, exist_ok=True)
    if db_name:
        export_database(db_name, str(sql_file))
        if settings.command_dry_run and not sql_file.exists():
            sql_file.write_text(f"-- DRY RUN database dump for {db_name}\n", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(website.root_path, arcname="site")
        if sql_file.exists():
            tar.add(sql_file, arcname=f"database/{sql_file.name}")
    return str(archive)


def save_uploaded_backup(domain: str, filename: str, source_file) -> str:
    backup_dir = (Path(settings.backup_root).resolve() / domain).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise ValueError("Only .tar.gz backup files are supported")
    target = (backup_dir / safe_name).resolve()
    if backup_dir not in target.parents:
        raise ValueError("Invalid backup filename")
    written = 0
    with target.open("wb") as buffer:
        while chunk := source_file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                target.unlink(missing_ok=True)
                raise ValueError("Backup file is too large")
            buffer.write(chunk)
    return str(target)


def restore_backup(website: Website, backup_file: str) -> str:
    archive = backup_path(website.domain, backup_file)
    _ensure_safe_tar(archive, Path(website.root_path).resolve())
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        has_site_prefix = any(member.name == "site" or member.name.startswith("site/") for member in members)
        for member in members:
            if member.name.startswith("database/"):
                continue
            if has_site_prefix:
                if member.name == "site":
                    continue
                if not member.name.startswith("site/"):
                    continue
                member.name = member.name[len("site/"):]
            tar.extract(member, website.root_path)
    return website.root_path


def backup_path(domain: str, backup_file: str) -> Path:
    backup_root = (Path(settings.backup_root).resolve() / domain).resolve()
    path = Path(backup_file).resolve()
    if backup_root not in path.parents or not path.exists() or path.suffixes[-2:] != [".tar", ".gz"] or not path.is_file():
        raise FileNotFoundError("Backup not found")
    return path


def _ensure_safe_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            member_path = (destination / member.name).resolve()
            if destination != member_path and destination not in member_path.parents:
                raise ValueError("Backup archive contains unsafe paths")
            if member.issym() or member.islnk():
                link_path = (member_path.parent / member.linkname).resolve()
                if destination != link_path and destination not in link_path.parents:
                    raise ValueError("Backup archive contains unsafe links")


def delete_backup(domain: str, backup_file: str) -> str:
    path = backup_path(domain, backup_file)
    path.unlink()
    return str(path)


def list_backups(domain: str) -> List[str]:
    backup_dir = Path(settings.backup_root) / domain
    if settings.command_dry_run:
        return []
    if not backup_dir.exists():
        return []
    return [str(path) for path in sorted(backup_dir.glob("*.tar.gz"), reverse=True)]
