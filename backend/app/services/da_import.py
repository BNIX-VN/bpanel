"""Import DirectAdmin backup archives into BPanel via the web panel.

Uploads are saved to ``DA_BACKUP_DIR`` (default ``/home/admin/bpanel_backups/da``).
An admin can then *scan* a backup to preview users/domains/databases, and
*import* it to create BPanel users, websites, nginx vhosts, MariaDB databases,
and optionally SSL certificates.
"""

from __future__ import annotations

import bz2
import datetime as _dt
import gzip
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import DatabaseAccount, User, Website, WebsiteAlias
from app.services import mariadb, nginx, site_users, waf
from app.services.shell import shell

logger = logging.getLogger("bpanel.da_import")

DA_BACKUP_DIR = Path(os.environ.get("BPANEL_DA_BACKUP_DIR", "/home/admin/bpanel_backups/da"))
STAGE_BASE = Path(os.environ.get("DA_IMPORT_STAGE_BASE", "/var/lib/bpanel/da-import"))
DEFAULT_PHP_VERSION = os.environ.get("DA_IMPORT_PHP", "8.3")
DEFAULT_STORAGE_MB = int(os.environ.get("DA_IMPORT_STORAGE_MB", "102400"))

DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{2,31}$")
DB_RE = re.compile(r"^[a-z0-9_]{1,64}$")

RESERVED_USERS = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail",
    "news", "uucp", "proxy", "www-data", "backup", "list", "irc", "_apt",
    "nobody", "bpanel", "bpanel-sites", "bpanel-sftp", "mysql", "redis", "nginx",
    "admin",
}

ARCHIVE_SUFFIXES = (
    ".tar.zst", ".tzst", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar",
)
SQL_SUFFIXES = (".sql", ".sql.gz", ".sql.bz2", ".sql.zst")

SQL_DATABASE_DIRECTIVE_RE = re.compile(
    r"^\s*(?:/\*![0-9]{5}\s*)?(?:CREATE\s+DATABASE|DROP\s+DATABASE|USE)\b",
    re.IGNORECASE,
)
SQL_DEFINER_RE = re.compile(
    r"DEFINER\s*=\s*(?:`[^`]*`|'[^']*'|\"[^\"]*\"|[^\s*/]+)\s*@\s*(?:`[^`]*`|'[^']*'|\"[^\"]*\"|[^\s*/]+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    logger.info(msg)
    print(msg, flush=True)


def _utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def _is_archive(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and any(name.endswith(s) for s in ARCHIVE_SUFFIXES)


def _strip_archive_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _archive_username(name: str) -> str:
    base = _strip_archive_suffix(name)
    pieces = [p for p in re.split(r"[._-]+", base) if p]
    if len(pieces) >= 3 and pieces[0] in {"user", "reseller"}:
        return pieces[-1]
    for piece in reversed(pieces):
        if piece.lower() not in {"backup", "user", "admin", "reseller"}:
            return piece
    return base


def _normalize_username(raw: str, archive_name: str = "") -> str:
    value = (raw or "").strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value).strip("_-")
    if not value or not re.match(r"^[a-z_]", value):
        value = f"da_{value}" if value else "da_user"
    value = value[:32]
    if len(value) < 3:
        value = f"{value}_da"[:32]
    if value in RESERVED_USERS or not USER_RE.fullmatch(value):
        digest = hashlib.sha1((raw + archive_name).encode("utf-8")).hexdigest()[:8]
        stem = re.sub(r"[^a-z0-9_]+", "_", value).strip("_") or "user"
        value = f"da_{stem[:18]}_{digest}"[:32]
    return value


def _normalize_domain(value: str) -> Optional[str]:
    domain = (value or "").strip().lower().rstrip(".")
    return domain if DOMAIN_RE.fullmatch(domain) else None


def _normalize_db_identifier(raw: str, fallback: str, existing: set[str]) -> str:
    value = (raw or fallback).strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
    if not value:
        value = fallback
    if not re.match(r"^[a-z0-9_]+$", value):
        value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = value[:64]
    if value not in existing and DB_RE.fullmatch(value):
        return value
    digest = hashlib.sha1((raw + fallback).encode("utf-8")).hexdigest()[:6]
    stem = (value[:55].strip("_") or fallback[:55].strip("_") or "db")
    candidate = f"{stem}_{digest}"[:64]
    counter = 2
    while candidate in existing or not DB_RE.fullmatch(candidate):
        suffix = f"_{counter}"
        candidate = f"{stem[:64 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def _read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        values[key.strip().lower()] = value.strip().strip("'\"")
    return values


def _server_ip_addresses() -> set[str]:
    addresses: set[str] = set()
    try:
        result = subprocess.run(
            ["ip", "-j", "address", "show", "scope", "global"],
            check=False, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for interface in json.loads(result.stdout or "[]"):
                for address in interface.get("addr_info", []):
                    local = address.get("local")
                    if local:
                        try:
                            addresses.add(str(ipaddress.ip_address(local)))
                        except ValueError:
                            pass
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired, ValueError):
        pass
    return addresses


def _domain_ip_addresses(domain: str) -> set[str]:
    addresses: set[str] = set()
    try:
        for item in socket.getaddrinfo(domain, None, type=socket.SOCK_STREAM):
            value = item[4][0].split("%", 1)[0]
            try:
                addresses.add(str(ipaddress.ip_address(value)))
            except ValueError:
                pass
    except socket.gaierror:
        pass
    return addresses


# ---------------------------------------------------------------------------
# Backup discovery
# ---------------------------------------------------------------------------

def _find_backup_root(extracted: Path) -> Path:
    if (extracted / "backup").exists() or (extracted / "domains").exists() or (extracted / "mysql").exists():
        return extracted
    candidates = []
    for path in extracted.rglob("backup"):
        if not path.is_dir():
            continue
        parent = path.parent
        score = 1
        if (parent / "domains").exists():
            score += 3
        if (parent / "mysql").exists():
            score += 2
        if (path / "user.conf").exists():
            score += 3
        candidates.append((score, parent))
    if candidates:
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]
    return extracted


def _discover_username(root: Path, archive_name: str) -> tuple[str, str]:
    user_conf = _read_key_values(root / "backup" / "user.conf")
    raw = (
        user_conf.get("username")
        or user_conf.get("user")
        or user_conf.get("account")
        or _archive_username(archive_name)
    )
    email = user_conf.get("email") or user_conf.get("emailaddress") or ""
    return _normalize_username(raw, archive_name), email


def _discover_domains(root: Path) -> list[str]:
    found: list[str] = []
    domains_list = root / "backup" / "domains.list"
    if domains_list.exists():
        for line in domains_list.read_text(encoding="utf-8", errors="ignore").splitlines():
            domain = _normalize_domain(line)
            if domain and domain not in found:
                found.append(domain)
    backup_dir = root / "backup"
    if backup_dir.exists():
        for item in backup_dir.iterdir():
            if item.is_file() and item.name.endswith(".conf"):
                domain = _normalize_domain(item.name[:-5])
                if domain and domain not in found:
                    found.append(domain)
    domains_dir = root / "domains"
    if domains_dir.exists():
        for item in domains_dir.iterdir():
            if item.is_dir():
                domain = _normalize_domain(item.name)
                if domain and domain not in found:
                    found.append(domain)
    return found


def _source_for_domain(root: Path, domain: str) -> Optional[Path]:
    candidates = [
        root / "domains" / domain / "public_html",
        root / "domains" / domain / "private_html",
        root / "domains" / domain,
        root / domain / "public_html",
        root / domain,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            if candidate.name == domain and (candidate / "public_html").exists():
                return candidate / "public_html"
            return candidate
    for path in root.rglob("public_html"):
        if path.is_dir() and domain in {part.lower() for part in path.parts}:
            return path
    return None


def _has_php_files(path: Path) -> bool:
    return any(item.is_file() and item.suffix.lower() in {".php", ".phtml"} for item in path.rglob("*"))


def _detect_app_type(source: Optional[Path]) -> str:
    if not source:
        return "php"
    if (source / "wp-config.php").exists() or (source / "wp-config-sample.php").exists():
        return "wordpress"
    return "php" if _has_php_files(source) else "static"


def _sql_base_name(path: Path) -> str:
    name = path.name
    for suffix in SQL_SUFFIXES:
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _discover_sql_files(root: Path) -> dict[str, Path]:
    preferred = [root / "mysql", root / "backup"]
    files: list[Path] = []
    for directory in preferred:
        if directory.exists():
            files.extend(
                path for path in directory.rglob("*")
                if path.is_file() and any(path.name.lower().endswith(s) for s in SQL_SUFFIXES)
            )
    if not files:
        for path in root.rglob("*"):
            if path.is_file() and any(path.name.lower().endswith(s) for s in SQL_SUFFIXES):
                if "domains" not in {part.lower() for part in path.parts}:
                    files.append(path)
    result: dict[str, Path] = {}
    for path in files:
        result.setdefault(_sql_base_name(path).lower(), path)
    return result


def _temporary_sql_file(sql_file: Path) -> Path:
    lower = sql_file.name.lower()
    tmp = Path(tempfile.mkstemp(prefix="bpanel-da-", suffix=".sql")[1])
    if lower.endswith(".sql"):
        opener = open
    elif lower.endswith(".gz"):
        opener = gzip.open
    elif lower.endswith(".bz2"):
        opener = bz2.open
    elif lower.endswith(".zst"):
        zstd = shutil.which("zstdcat") or shutil.which("zstd")
        if not zstd:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("zstd is required to import .sql.zst files. Install package: zstd")
        args = [zstd, str(sql_file)] if Path(zstd).name == "zstdcat" else [zstd, "-dc", str(sql_file)]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        try:
            with tmp.open("w", encoding="utf-8") as target:
                assert proc.stdout is not None
                for line in proc.stdout:
                    if SQL_DATABASE_DIRECTIVE_RE.match(line):
                        continue
                    target.write(SQL_DEFINER_RE.sub("", line))
            _, stderr = proc.communicate(timeout=30)
            if proc.returncode != 0:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(stderr.strip() or "zstd SQL decompression failed")
            return tmp
        finally:
            if proc.poll() is None:
                proc.kill()
    else:
        raise RuntimeError(f"Unsupported SQL compression: {sql_file}")
    with opener(sql_file, "rt", encoding="utf-8", errors="replace") as source, tmp.open("w", encoding="utf-8") as target:
        for line in source:
            if SQL_DATABASE_DIRECTIVE_RE.match(line):
                continue
            target.write(SQL_DEFINER_RE.sub("", line))
    return tmp


# ---------------------------------------------------------------------------
# App config parsing
# ---------------------------------------------------------------------------

def _parse_wp_config(path: Path) -> dict[str, str]:
    config = path / "wp-config.php"
    if not config.exists():
        return {}
    text = config.read_text(encoding="utf-8", errors="ignore")
    found: dict[str, str] = {}
    for key in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"):
        match = re.search(r"define\s*\(\s*['\"]" + key + r"['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)", text)
        if match:
            found[key] = match.group(1)
    return found


def _parse_dotenv_config(path: Path) -> dict[str, str]:
    env_file = path / ".env"
    if not env_file.exists():
        return {}
    values = _read_key_values(env_file)
    result: dict[str, str] = {}
    if values.get("db_database"):
        result["DB_NAME"] = values["db_database"]
    if values.get("db_username"):
        result["DB_USER"] = values["db_username"]
    if values.get("db_password"):
        result["DB_PASSWORD"] = values["db_password"]
    if values.get("db_host"):
        result["DB_HOST"] = values["db_host"]
    return result


def _parse_php_variable_config(path: Path) -> dict[str, str]:
    config = path / "configuration.php"
    if not config.exists():
        return {}
    text = config.read_text(encoding="utf-8", errors="ignore")
    mappings = {
        "DB_NAME": ("db", "db_name", "database", "db_database"),
        "DB_USER": ("user", "dbuser", "db_user", "db_username", "username"),
        "DB_PASSWORD": ("password", "dbpass", "db_password"),
        "DB_HOST": ("host", "db_host"),
    }
    result: dict[str, str] = {}
    for key, names in mappings.items():
        for name in names:
            match = re.search(r"(?:public\s+)?\$" + re.escape(name) + r"\s*=\s*['\"]([^'\"]*)['\"]\s*;", text)
            if match:
                result[key] = match.group(1)
                break
    return result


def _parse_app_db_config(path: Path) -> dict[str, str]:
    for parser in (_parse_wp_config, _parse_dotenv_config, _parse_php_variable_config):
        values = parser(path)
        if values.get("DB_NAME"):
            return values
    return {}


def _replace_define(text: str, key: str, value: str) -> str:
    pattern = re.compile(r"(define\s*\(\s*['\"]" + key + r"['\"]\s*,\s*)['\"][^'\"]*['\"](\s*\)\s*;)")
    if pattern.search(text):
        return pattern.sub(lambda m: f"{m.group(1)}'{value}'{m.group(2)}", text, count=1)
    return text + f"\ndefine('{key}', '{value}');\n"


def _update_app_db_config(public: Path, db_name: str, db_user: str, db_password: str) -> None:
    wp = public / "wp-config.php"
    if wp.exists():
        text = wp.read_text(encoding="utf-8", errors="ignore")
        text = _replace_define(text, "DB_NAME", db_name)
        text = _replace_define(text, "DB_USER", db_user)
        text = _replace_define(text, "DB_PASSWORD", db_password)
        text = _replace_define(text, "DB_HOST", "localhost")
        wp.write_text(text, encoding="utf-8")

    env_file = public / ".env"
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        replacements = {
            "DB_DATABASE": db_name,
            "DB_USERNAME": db_user,
            "DB_PASSWORD": db_password,
            "DB_HOST": "127.0.0.1",
        }
        out = []
        seen = set()
        for line in lines:
            stripped = line.strip()
            matched = False
            for env_key, env_val in replacements.items():
                if stripped.lower().startswith(f"{env_key.lower()}=") or stripped.lower().startswith(f"{env_key.lower()} ="):
                    out.append(f"{env_key}={env_val}")
                    seen.add(env_key)
                    matched = True
                    break
            if not matched:
                out.append(line)
        for env_key, env_val in replacements.items():
            if env_key not in seen:
                out.append(f"{env_key}={env_val}")
        env_file.write_text("\n".join(out) + "\n", encoding="utf-8")

    config_php = public / "configuration.php"
    if config_php.exists():
        text = config_php.read_text(encoding="utf-8", errors="ignore")
        for key, value in [
            ("db", db_name), ("db_name", db_name),
            ("user", db_user), ("dbuser", db_user), ("db_username", db_user),
            ("password", db_password), ("dbpass", db_password), ("db_password", db_password),
            ("host", "localhost"), ("db_host", "localhost"),
        ]:
            text = re.sub(
                r"(public\s+\$?" + re.escape(key) + r"\s*=\s*)['\"][^'\"]*['\"](\s*;)",
                rf"\1'{value}'\2", text, count=1,
            )
        config_php.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def _copy_site_files(source: Optional[Path], public: Path) -> None:
    public.mkdir(parents=True, exist_ok=True)
    if not source or not source.exists():
        return
    for root_dir, dirs, files in os.walk(source):
        root_path = Path(root_dir)
        rel_root = root_path.relative_to(source)
        target_root = public / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        dirs[:] = [name for name in dirs if not (root_path / name).is_symlink()]
        for name in files:
            src = root_path / name
            if src.is_symlink() or not src.is_file():
                continue
            dst = target_root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _clear_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    proc = None
    if archive.name.lower().endswith((".tar.zst", ".tzst")):
        zstd = shutil.which("zstdcat") or shutil.which("zstd")
        if not zstd:
            raise RuntimeError("zstd is required to extract .tar.zst backups. Install package: zstd")
        args = [zstd, str(archive)] if Path(zstd).name == "zstdcat" else [zstd, "-dc", str(archive)]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tar = tarfile.open(fileobj=proc.stdout, mode="r|")
    else:
        tar = tarfile.open(archive, "r:*")
    try:
        base_resolved = destination.resolve()
        for member in tar:
            member_path = (destination / member.name).resolve()
            try:
                member_path.relative_to(base_resolved)
            except ValueError:
                raise RuntimeError(f"Unsafe path in {archive.name}: {member.name}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"Unsafe link in {archive.name}: {member.name}")
        tar.extractall(path=str(destination), filter="data")
    finally:
        tar.close()
        if proc is not None:
            proc.wait()
            if proc.returncode != 0:
                stderr = (proc.stderr or b"").read() if hasattr(proc.stderr, "read") else b""
                raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "zstd extraction failed")


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def _existing_identifiers(db) -> tuple[set[str], set[str]]:
    rows = db.query(DatabaseAccount).all()
    return {row.db_name for row in rows}, {row.db_user for row in rows}


def _matched_sql_for_config(
    app_config: dict[str, str],
    sql_files: dict[str, Path],
    single_site: bool,
) -> tuple[str, Optional[Path]]:
    if app_config.get("DB_NAME"):
        key = app_config["DB_NAME"].lower()
        if key in sql_files:
            return key, sql_files[key]
    if single_site and len(sql_files) == 1:
        return next(iter(sql_files.items()))
    return "", None


def _unique_email(db, username: str, preferred: str, domains: list[str]) -> str:
    domain = domains[0] if domains else "import.local"
    base = preferred if preferred and "@" in preferred else f"{username}@{domain}"
    local, _, host = base.partition("@")
    local = re.sub(r"[^A-Za-z0-9_.+-]+", ".", local).strip(".") or username
    host = host or domain
    candidate = f"{local}@{host}"
    counter = 2
    while db.query(User).filter(User.email == candidate).first():
        candidate = f"{local}+{counter}@{host}"
        counter += 1
    return candidate


def _delete_database_record(db, db_item) -> None:
    try:
        mariadb.drop_database(db_item.db_name, db_item.db_user)
    finally:
        db.delete(db_item)
        db.flush()


def _delete_website_record(db, website) -> None:
    for db_item in db.query(DatabaseAccount).filter(DatabaseAccount.website_id == website.id).all():
        _delete_database_record(db, db_item)
    try:
        nginx.delete_wordpress_vhost(website.domain)
    finally:
        try:
            from app.services import wordpress
            wordpress.delete_wordpress(website.root_path)
        except Exception:
            pass
        db.delete(website)
        db.flush()


def _delete_existing_domain(db, domain: str) -> bool:
    website = db.query(Website).filter(Website.domain == domain).first()
    if not website:
        return False
    _log(f"  deleting existing domain before import: {domain}")
    _delete_website_record(db, website)
    db.commit()
    return True


def _delete_existing_user(db, username: str) -> bool:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return False
    _log(f"  deleting existing user before import: {username}")
    for website in db.query(Website).filter(Website.owner_id == user.id).order_by(Website.id.asc()).all():
        _delete_website_record(db, website)
    for db_item in db.query(DatabaseAccount).filter(DatabaseAccount.owner_id == user.id).all():
        _delete_database_record(db, db_item)
    site_users.delete_panel_user(username)
    db.delete(user)
    db.commit()
    return True


def _ensure_panel_user_record(db, username: str, email: str, domains: list[str], credentials: list[str]):
    password = secrets.token_urlsafe(18)
    site_users.ensure_panel_user(username, password)
    user = User(
        username=username,
        email=_unique_email(db, username, email, domains),
        hashed_password=hash_password(password),
        role="end_user",
        website_limit=max(5, len(domains) + 5),
        storage_limit_mb=DEFAULT_STORAGE_MB,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    credentials.append(f"panel_user username={username} password={password}")
    return user, True


def _create_panel_database(
    db, owner, website, old_db: str, old_user: Optional[str],
    sql_file: Optional[Path], credentials: list[str],
) -> tuple[str, str, str]:
    used_names, used_users = _existing_identifiers(db)
    fallback = mariadb.safe_db_identifier(
        website.domain if website else owner.username, "da"
    )
    db_name = _normalize_db_identifier(old_db, fallback, used_names)
    db_user = _normalize_db_identifier(old_user or db_name, f"u_{db_name}"[:64], used_users)
    db_password = mariadb.random_password()

    mariadb.create_database_credentials(db_name, db_user, db_password)
    temp_sql: Optional[Path] = None
    try:
        if sql_file is not None:
            temp_sql = _temporary_sql_file(sql_file)
            mariadb.import_database(db_name, str(temp_sql))
    except Exception:
        mariadb.drop_database(db_name, db_user)
        raise
    finally:
        if temp_sql is not None:
            temp_sql.unlink(missing_ok=True)

    from app.core.secrets import encrypt
    item = DatabaseAccount(
        owner_id=owner.id,
        website_id=website.id if website else None,
        db_name=db_name,
        db_user=db_user,
        db_password=encrypt(db_password),
    )
    db.add(item)
    db.commit()
    target = website.domain if website else owner.username
    credentials.append(f"database target={target} db_name={db_name} db_user={db_user} db_password={db_password}")
    return db_name, db_user, db_password


def _enable_ssl_when_dns_matches(db, website, item_summary: dict) -> None:
    from app.services import ssl as ssl_service
    try:
        domain_ips = _domain_ip_addresses(website.domain)
    except Exception as exc:
        item_summary["warnings"].append(f"SSL skipped for {website.domain}: DNS lookup failed ({exc})")
        return
    server_ips = _server_ip_addresses()
    matching_ips = domain_ips & server_ips
    if not matching_ips:
        return
    _log(f"  DNS matches ({', '.join(sorted(matching_ips))}); installing SSL for {website.domain} ...")
    result = ssl_service.issue_ssl(website.domain)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "certbot failed").strip().replace("\n", " ")
        item_summary["warnings"].append(f"SSL failed for {website.domain}: {detail[:500]}")
        return
    website.ssl_enabled = True
    db.commit()
    db.refresh(website)
    item_summary["ssl_enabled_domains"].append(website.domain)
    _log(f"  SSL installed for {website.domain}")


# ---------------------------------------------------------------------------
# Public API — Scan
# ---------------------------------------------------------------------------

def list_da_backups() -> list[dict]:
    """Return metadata for every DA backup archive in the upload directory."""
    if not DA_BACKUP_DIR.exists():
        return []
    items = []
    for path in sorted(DA_BACKUP_DIR.iterdir()):
        if _is_archive(path):
            items.append({
                "filename": path.name,
                "path": str(path),
                "size": path.stat().st_size,
            })
    return items


def scan_da_backup(archive_path: str) -> dict:
    """Extract a DA backup into a temp dir, discover users/domains/databases."""
    path = Path(archive_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup not found: {archive_path}")
    if not _is_archive(path):
        raise ValueError("Not a supported archive format")

    result: dict = {
        "filename": path.name,
        "size": path.stat().st_size,
        "archive_path": str(path),
        "users": [],
        "errors": [],
    }

    with tempfile.TemporaryDirectory(prefix="bpanel-da-scan-") as tmp:
        extracted = Path(tmp) / "extracted"
        try:
            _safe_extract_tar(path, extracted)
        except Exception as exc:
            result["errors"].append(f"Extraction failed: {exc}")
            return result

        root = _find_backup_root(extracted)
        username, email = _discover_username(root, path.name)
        domains = _discover_domains(root)
        sql_files = _discover_sql_files(root)

        user_entry: dict = {
            "username": username,
            "email": email,
            "domains": [],
            "databases": [],
        }

        for domain in domains:
            source = _source_for_domain(root, domain)
            app_type = _detect_app_type(source)
            app_config = _parse_app_db_config(source) if source else {}
            matched_key, matched_sql = _matched_sql_for_config(app_config, sql_files, len(domains) == 1)

            domain_entry: dict = {
                "domain": domain,
                "app_type": app_type,
                "has_files": source is not None,
                "db_name": app_config.get("DB_NAME") or matched_key or "",
                "db_user": app_config.get("DB_USER") or "",
                "has_sql_dump": matched_sql is not None,
            }
            user_entry["domains"].append(domain_entry)

        # Unassigned databases
        assigned_keys = set()
        for d in user_entry["domains"]:
            if d["db_name"]:
                assigned_keys.add(d["db_name"].lower())
        for key, sql_path in sql_files.items():
            if key not in assigned_keys:
                user_entry["databases"].append({
                    "db_name": key,
                    "sql_file": str(sql_path),
                    "has_sql_dump": True,
                })

        result["users"].append(user_entry)

    return result


# ---------------------------------------------------------------------------
# Public API — Import
# ---------------------------------------------------------------------------

def import_da_backup(archive_path: str, force: bool = False) -> dict:
    """Import a DA backup archive into BPanel.

    Creates panel users, websites, nginx vhosts, MariaDB databases, and
    optionally SSL certificates.

    Returns a summary dict with credentials (passwords are generated).
    """
    path = Path(archive_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup not found: {archive_path}")
    if not _is_archive(path):
        raise ValueError("Not a supported archive format")

    stamp = _utc_stamp()
    stage_dir = STAGE_BASE / f"web-{stamp}-{secrets.token_hex(4)}"
    stage_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict] = []
    credentials: list[str] = [
        "# BPanel DirectAdmin import credentials",
        f"# Web import: {stamp}",
        f"# Archive: {path.name}",
        "# Keep this file private. It contains generated panel and database passwords.",
    ]

    try:
        extracted = stage_dir / "extracted"
        _log(f"Extracting {path.name} ...")
        _safe_extract_tar(path, extracted)

        root = _find_backup_root(extracted)
        domains = _discover_domains(root)
        username, email = _discover_username(root, path.name)

        item_summary: dict = {
            "archive": path.name,
            "username": username,
            "domains": domains,
            "imported_domains": [],
            "databases": [],
            "ssl_enabled_domains": [],
            "warnings": [],
        }

        if not domains:
            item_summary["warnings"].append("No domains found")
            summary.append(item_summary)
            return {"summary": summary, "credentials": credentials, "errors": ["No domains found"]}

        db = SessionLocal()
        try:
            for domain in domains:
                _delete_existing_domain(db, domain)
            _delete_existing_user(db, username)

            user, created = _ensure_panel_user_record(db, username, email, domains, credentials)

            sql_files = _discover_sql_files(root)
            imported_sql_keys: set[str] = set()
            websites = []

            for domain in domains:
                source = _source_for_domain(root, domain)
                app_type = _detect_app_type(source)
                app_config = _parse_app_db_config(source) if source else {}

                _log(f"Importing domain {domain} for user {username} ...")

                root_path = site_users.site_root_for_panel_user(user.username, domain)
                linux_user = site_users.ensure_site_runtime(
                    domain, root_path,
                    DEFAULT_PHP_VERSION if app_type in {"wordpress", "php"} else None,
                    user.username,
                )
                public = site_users.document_root(root_path)
                _clear_directory(public)
                _copy_site_files(source, public)

                selected_rules = [rule["id"] for rule in waf.DEFAULT_RULES]
                waf_enabled = True
                waf_result = waf.sync_site_rules(domain, selected_rules, "")
                if waf_result.returncode != 0:
                    waf_enabled = False
                    _log(f"  warning: WAF rules failed for {domain}")

                php_socket = site_users.site_php_fpm_socket(
                    linux_user, root_path,
                    DEFAULT_PHP_VERSION if app_type in {"wordpress", "php"} else None,
                )
                try:
                    nginx.write_vhost(
                        domain, root_path,
                        app_type=app_type,
                        php_version=DEFAULT_PHP_VERSION if app_type in {"wordpress", "php"} else None,
                        php_fpm_socket_override=php_socket,
                        waf_enabled=waf_enabled,
                    )
                except RuntimeError:
                    if not waf_enabled:
                        raise
                    waf_enabled = False
                    _log(f"  warning: nginx rejected WAF for {domain}; retrying with WAF disabled")
                    nginx.write_vhost(
                        domain, root_path,
                        app_type=app_type,
                        php_version=DEFAULT_PHP_VERSION if app_type in {"wordpress", "php"} else None,
                        php_fpm_socket_override=php_socket,
                        waf_enabled=False,
                    )

                website = db.query(Website).filter(Website.domain == domain).first()
                if website is None:
                    website = Website(
                        domain=domain,
                        owner_id=user.id,
                        root_path=root_path,
                        linux_user=linux_user,
                        php_version=DEFAULT_PHP_VERSION,
                        app_type=app_type,
                        status="active",
                        waf_enabled=waf_enabled,
                    )
                    db.add(website)
                else:
                    website.owner_id = user.id
                    website.root_path = root_path
                    website.linux_user = linux_user
                    website.php_version = DEFAULT_PHP_VERSION
                    website.app_type = app_type
                    website.waf_enabled = waf_enabled
                db.commit()
                db.refresh(website)
                site_users.fix_site_permissions(root_path, linux_user)
                websites.append(website)
                item_summary["imported_domains"].append(domain)

                # Database import
                public = site_users.document_root(website.root_path)
                app_config = app_config or _parse_app_db_config(public)
                matched_key, matched_sql = _matched_sql_for_config(app_config, sql_files, len(domains) == 1)
                if matched_sql:
                    db_name, db_user, db_password = _create_panel_database(
                        db, user, website,
                        app_config.get("DB_NAME") or matched_key,
                        app_config.get("DB_USER"),
                        matched_sql, credentials,
                    )
                    imported_sql_keys.add(matched_key)
                    _update_app_db_config(public, db_name, db_user, db_password)
                    site_users.fix_site_permissions(website.root_path, website.linux_user)
                    item_summary["databases"].append({
                        "domain": domain, "source": str(matched_sql), "db_name": db_name,
                    })

            # Import unassigned databases
            for key, sql_path in sql_files.items():
                if key in imported_sql_keys:
                    continue
                if db.query(DatabaseAccount).filter(DatabaseAccount.db_name == key).first() and not force:
                    continue
                _log(f"Importing unassigned database {key} for user {username} ...")
                db_name, db_user, _db_password = _create_panel_database(
                    db, user, None, key, key, sql_path, credentials,
                )
                item_summary["databases"].append({
                    "domain": None, "source": str(sql_path), "db_name": db_name, "db_user": db_user,
                })

            # SSL auto-setup
            for website in websites:
                _enable_ssl_when_dns_matches(db, website, item_summary)

            summary.append(item_summary)
        finally:
            db.close()

    finally:
        # Cleanup staging
        shutil.rmtree(stage_dir, ignore_errors=True)

    errors = [w for item in summary for w in item.get("warnings", []) if "failed" in w.lower() or "error" in w.lower()]
    return {
        "summary": summary,
        "credentials": credentials,
        "errors": errors,
    }


def delete_da_backup(archive_path: str) -> str:
    """Delete an uploaded DA backup archive."""
    path = Path(archive_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup not found: {archive_path}")
    # Safety: only allow deleting files inside DA_BACKUP_DIR
    try:
        path.resolve().relative_to(DA_BACKUP_DIR.resolve())
    except ValueError:
        raise ValueError("Can only delete files from the DA backup directory")
    name = path.name
    path.unlink(missing_ok=True)
    return name
