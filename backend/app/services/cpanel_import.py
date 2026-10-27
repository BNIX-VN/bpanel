"""Import cPanel account backups (the cPanel Import addon, operator 2026-10-27:
"bpanel không có các addon import cpanel, import DirectAdmin, import FastPanel"
- as OPanel's, whose cpanel_import.py this follows).

A cPanel backup - ``cpmove-<user>.tar.gz`` from pkgacct, or the
``backup-<date>_<time>_<user>.tar.gz`` a cPanel backup run writes - is laid
out the way a DirectAdmin backup is, then imported by the DirectAdmin importer
(da_import.import_laid_out): one importer for users, websites with their Nginx
vhosts and PHP-FPM pools, databases, aliases and certificates, with two archive
layouts in front of it.

What a cPanel archive holds, and where it goes:

- ``cp/<user>``: the account - ``USER=``, ``CONTACTEMAIL=``, ``DNS=`` the
  main domain;
- ``userdata/main``: the main domain, the addon domains (each backed by a
  subdomain of the main one, which is not a website of its own), the parked
  domains and the subdomains;
- ``userdata/<domain>``: each one's ``documentroot`` and ``phpversion``;
- ``homedir/`` (or ``homedir.tar``): the home folder the document roots are in.
  cPanel nests addon domains and subdomains inside public_html; each is moved
  out before its parent is, so no files are imported twice;
- ``mysql/<db>.sql``: the databases (the grants in ``mysql.sql`` carry only
  password hashes; the importer takes the password from the site's config);
- ``apache_tls/<domain>``: the certificate, its key and chain in one PEM file.

Parked domains become aliases of the main website: they are written as the
main domain's DirectAdmin pointers, which the importer already turns into
aliases in the vhost and on the certificate. Mail, cron jobs and DNS zones are
counted and reported, not imported.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from app.models.entities import Website
from app.services import da_import

BACKUP_DIR = Path(os.environ.get("BPANEL_CPANEL_BACKUP_DIR", "/home/admin/bpanel_backups/cpanel"))
# Only the default is one the helper knows how to create (da-backup-dir-ensure).
BACKUP_DIR_IS_DEFAULT = "BPANEL_CPANEL_BACKUP_DIR" not in os.environ
# cpmove-<user>.tar.gz (pkgacct) and backup-<M.D.YYYY>_<H-M-S>_<user>.tar.gz
# (a cPanel backup run).
NAME_RE = re.compile(
    r"^(?:cpmove-(?P<a>[a-z0-9][a-z0-9_.-]{0,31})"
    r"|backup-\d{1,2}\.\d{1,2}\.\d{4}_\d{1,2}-\d{1,2}-\d{1,2}_(?P<b>[a-z0-9][a-z0-9_.-]{0,31}))"
    r"\.(?:tar\.gz|tgz|tar)$",
    re.IGNORECASE,
)
# Databases cPanel itself keeps beside the account's own; never the customer's.
SYSTEM_DATABASES = frozenset({"roundcube", "horde", "cphulkd", "eximstats", "leechprotect", "modsec", "whmxfer", "mysql"})
# A certificate file bigger than this is not a certificate.
MAX_PEM_BYTES = 512 * 1024


class CPanelImportError(RuntimeError):
    """A cPanel archive that cannot be imported, phrased for the panel."""


def _log(msg: str) -> None:
    da_import._log(f"[cpanel] {msg}")


# --- names and the folder -------------------------------------------------------

def _base(name: str) -> str:
    return (name or "").replace("\\", "/").rsplit("/", 1)[-1]


def is_cpanel_name(name: str) -> bool:
    return bool(NAME_RE.match(_base(name)))


def account_of(name: str) -> str:
    match = NAME_RE.match(_base(name))
    return (match.group("a") or match.group("b") or "").lower() if match else ""


def ensure_backup_dir() -> None:
    da_import.ensure_import_dir(BACKUP_DIR, BACKUP_DIR_IS_DEFAULT)


def resolve_path(archive_path: str) -> Path:
    """The cPanel archive a name or path names, inside BACKUP_DIR only.

    The restore job hands this a path it built itself, but it is checked again
    here the way da_import.resolve_backup_path checks its own: confined to the
    folder, a plain file, and named the way cPanel names its backups.
    """
    raw = (archive_path or "").strip()
    if not raw:
        raise FileNotFoundError("Backup not found")
    folder = BACKUP_DIR.resolve()
    candidate = Path(raw)
    path = (candidate if candidate.is_absolute() else folder / candidate.name).resolve()
    if path.parent != folder or not path.is_file() or not is_cpanel_name(path.name):
        raise FileNotFoundError("Backup not found")
    return path


def free_name(name: str, folder: Path) -> str:
    """``name``, or - when that is taken - the name a cPanel backup run would
    give the same account now, which still says whose it is."""
    if not (folder / name).exists() and not (folder / f".{name}.part").exists():
        return name
    suffix = name[len(da_import._strip_archive_suffix(name)):]
    now = _dt.datetime.now(_dt.timezone.utc)
    return (f"backup-{now.month}.{now.day}.{now.year}_{now.hour}-{now.minute}-{now.second}"
            f"_{account_of(name)}{suffix}")


def save_upload(filename: str, source_file) -> Path:
    """An uploaded cPanel archive, into BACKUP_DIR: never over another one,
    and as a hidden .part until it is whole, so the list never offers half a
    file."""
    name = _base(filename).strip()
    if not is_cpanel_name(name):
        raise ValueError("Not a cPanel backup: expected cpmove-<user>.tar.gz or backup-<date>_<user>.tar.gz")
    ensure_backup_dir()
    if not os.access(BACKUP_DIR, os.W_OK):
        raise RuntimeError(f"Cannot write to {BACKUP_DIR}. Run bpanel-update.")
    destination = BACKUP_DIR / free_name(name, BACKUP_DIR)
    if destination.exists():
        raise ValueError(f"{destination.name} is already waiting to be restored; delete it first")
    partial = BACKUP_DIR / f".{destination.name}.part"
    try:
        with open(partial, "wb") as out:
            while chunk := source_file.read(1024 * 1024):
                out.write(chunk)
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination


# --- reading the archive ------------------------------------------------------------

def parse_userdata(text: str) -> dict:
    """cPanel's userdata YAML, as far as it goes: top-level keys whose value is
    a scalar, a list ("  - item") or a map ("  key: value"). No YAML library:
    the panel has none, and this is all cPanel writes there."""
    data: dict = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw.strip() == "---":
            continue
        if not raw.startswith((" ", "\t")):
            key, _, value = raw.partition(":")
            current = key.strip().strip("'\"")
            value = value.strip()
            data[current] = _scalar(value) if value and value not in {"{}", "[]"} else ([] if value == "[]" else {})
            continue
        if current is None:
            continue
        line = raw.strip()
        if line.startswith("- "):
            if not isinstance(data.get(current), list):
                data[current] = []
            data[current].append(_scalar(line[2:]))
        elif ":" in line:
            if not isinstance(data.get(current), dict):
                data[current] = {}
            key, _, value = line.partition(":")
            data[current][key.strip().strip("'\"")] = _scalar(value.strip())
    return data


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def _find_root(extracted: Path) -> Path:
    """The folder holding cp/ and userdata/: the archive's top folder, usually."""
    def looks_right(path: Path) -> bool:
        return (path / "userdata").is_dir() or (path / "cp").is_dir()

    if looks_right(extracted):
        return extracted
    for child in sorted(extracted.iterdir()):
        if child.is_dir() and looks_right(child):
            return child
    for child in sorted(extracted.iterdir()):
        if child.is_dir():
            for grandchild in sorted(child.iterdir()):
                if grandchild.is_dir() and looks_right(grandchild):
                    return grandchild
    raise CPanelImportError("Not a cPanel backup: it has no cp/ or userdata/ folder")


def _account(root: Path, archive_name: str) -> dict:
    """The account file cp/<user>: its name, contact email and main domain."""
    values: dict[str, str] = {}
    user = ""
    cp = root / "cp"
    if cp.is_dir():
        files = [path for path in sorted(cp.iterdir()) if path.is_file()]
        if files:
            user = files[0].name
            for line in files[0].read_text(encoding="utf-8", errors="ignore").splitlines():
                key, sep, value = line.partition("=")
                if sep:
                    values[key.strip().upper()] = value.strip()
    user = (values.get("USER") or user or account_of(archive_name)).strip().lower()
    if not user:
        raise CPanelImportError("The cPanel account name is not in the archive")
    return {"user": user, "email": values.get("CONTACTEMAIL", "").split(",")[0].strip(),
            "main": (values.get("DNS") or "").strip().lower()}


def _websites(root: Path, account: dict, warnings: list[str]) -> tuple[list[dict], list[str], str]:
    """The websites (domain, document root, PHP version), the parked domains,
    and the home folder the document roots are under."""
    main_data = {}
    main_file = root / "userdata" / "main"
    if main_file.is_file():
        main_data = parse_userdata(main_file.read_text(encoding="utf-8", errors="ignore"))
    main = (main_data.get("main_domain") or account["main"] or "").strip().lower()
    if not main:
        raise CPanelImportError("The archive does not name the account's main domain")
    addons = main_data.get("addon_domains") if isinstance(main_data.get("addon_domains"), dict) else {}
    subs = main_data.get("sub_domains") if isinstance(main_data.get("sub_domains"), list) else []
    parked = main_data.get("parked_domains") if isinstance(main_data.get("parked_domains"), list) else []
    # Each addon domain is served through a subdomain of the main one; that
    # subdomain is the addon's plumbing, not a website of its own.
    backing = {str(sub).lower() for sub in addons.values()}

    def site(domain: str, userdata_name: str) -> dict:
        data = {}
        path = root / "userdata" / userdata_name
        if path.is_file() and path.parent == root / "userdata":
            data = parse_userdata(path.read_text(encoding="utf-8", errors="ignore"))
        return {"domain": domain.lower(), "documentroot": str(data.get("documentroot") or ""),
                "homedir": str(data.get("homedir") or ""), "phpversion": str(data.get("phpversion") or "")}

    sites = [site(main, main)]
    if not sites[0]["documentroot"]:
        sites[0]["documentroot"] = f"/home/{account['user']}/public_html"
    for addon, sub in addons.items():
        sites.append(site(str(addon), str(sub)))
    for sub in subs:
        if str(sub).lower() not in backing:
            sites.append(site(str(sub), str(sub)))
    homedir = next((entry["homedir"] for entry in sites if entry["homedir"]), "") or f"/home/{account['user']}"
    kept, seen = [], set()
    for entry in sites:
        domain = da_import._normalize_domain(entry["domain"])
        if not domain:
            warnings.append(f"Skipped {entry['domain']!r}: not a domain name")
            continue
        if domain in seen:
            continue
        seen.add(domain)
        kept.append({**entry, "domain": domain})
    parked_names = []
    for name in parked:
        domain = da_import._normalize_domain(str(name))
        if domain and domain not in seen and domain not in parked_names:
            parked_names.append(domain)
    return kept, parked_names, homedir.rstrip("/")


def _home(root: Path) -> Optional[Path]:
    """The account's home folder from the archive, unpacked if it came as homedir.tar."""
    folder = root / "homedir"
    if folder.is_dir():
        return folder
    packed = root / "homedir.tar"
    if packed.is_file():
        folder.mkdir()
        da_import._safe_extract_tar(packed, folder)
        packed.unlink(missing_ok=True)
        return folder
    return None


def _split_pem(text: str) -> dict:
    """apache_tls/<domain>: the key, the certificate, then its chain, in one file."""
    keys, certificates = [], []
    for match in re.finditer(r"-----BEGIN ([A-Z ]+)-----.*?-----END \1-----", text, re.S):
        if "PRIVATE KEY" in match.group(1):
            keys.append(match.group(0))
        elif match.group(1) == "CERTIFICATE":
            certificates.append(match.group(0))
    return {"key": keys[0] if keys else "", "cert": certificates[0] if certificates else "",
            "chain": "\n".join(certificates[1:])}


# --- laying it out the DirectAdmin way ---------------------------------------------

def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _taken_here(names: list[str]) -> set[str]:
    """Which of these domains are websites on this server already. A parked
    domain that is one stays where it is instead of becoming an alias that
    Nginx would then serve twice."""
    if not names:
        return set()
    with da_import.SessionLocal() as db:
        return {domain for (domain,) in db.query(Website.domain).filter(Website.domain.in_(names))}


def _layout(root: Path, target: Path, account: dict, sites: list[dict], parked: list[str], homedir: str,
            warnings: list[str]) -> None:
    """Write ``target`` as the DirectAdmin importer reads a backup."""
    (target / "backup").mkdir(parents=True)
    (target / "domains").mkdir()
    (target / "mysql").mkdir()
    _write(target / "backup" / "user.conf", f"username={account['user']}\nemail={account['email']}\n")
    _write(target / "backup" / "domains.list", "".join(entry["domain"] + "\n" for entry in sites))

    home = _home(root)
    # Deepest document root first: cPanel keeps addon domains and subdomains
    # inside public_html, and each has to leave before its parent is moved.
    moved: dict[str, Path] = {}
    for entry in sorted(sites, key=lambda item: -len(Path(item["documentroot"] or "/").parts)):
        domain, docroot = entry["domain"], entry["documentroot"].rstrip("/")
        destination = target / "domains" / domain / "public_html"
        if not docroot or home is None:
            continue
        if docroot in moved:
            # Two websites on one folder: each gets its own copy.
            shutil.copytree(moved[docroot], destination, symlinks=True)
            continue
        if docroot != homedir and not docroot.startswith(homedir + "/"):
            warnings.append(f"{domain}: its files were outside the home folder ({docroot}) and are not in the archive")
            continue
        relative = docroot[len(homedir):].strip("/")
        source = (home / relative) if relative else None
        if source is None or ".." in Path(relative).parts or not source.is_dir() or source.is_symlink():
            warnings.append(f"{domain}: no files found at {docroot or '(none)'}; the website starts empty")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved[docroot] = destination

    sql_dir = root / "mysql"
    if sql_dir.is_dir():
        for path in sorted(sql_dir.iterdir()):
            lower = path.name.lower()
            if not path.is_file() or not lower.endswith(da_import.SQL_SUFFIXES):
                continue
            if da_import._sql_base_name(path).lower() in SYSTEM_DATABASES:
                continue
            shutil.move(str(path), str(target / "mysql" / path.name))

    tls = root / "apache_tls"
    if tls.is_dir():
        for entry in sites:
            pem = tls / entry["domain"]
            if not pem.is_file() or pem.stat().st_size > MAX_PEM_BYTES:
                continue
            parts = _split_pem(pem.read_text(encoding="utf-8", errors="ignore"))
            if not parts["key"] or not parts["cert"]:
                continue
            folder = target / "backup" / entry["domain"]
            folder.mkdir(parents=True, exist_ok=True)
            _write(folder / "domain.key", parts["key"] + "\n")
            _write(folder / "domain.cert", parts["cert"] + "\n")
            if parts["chain"]:
                _write(folder / "domain.cacert", parts["chain"] + "\n")

    # Parked domains: the main domain's pointers, as DirectAdmin writes them.
    taken = _taken_here(parked)
    for name in parked:
        if name in taken:
            warnings.append(f"Parked domain {name} is a website here already; not added as an alias")
    aliases = [name for name in parked if name not in taken]
    if aliases and sites:
        _write(target / "backup" / f"{sites[0]['domain']}.pointers", "".join(f"{name}=alias\n" for name in aliases))


def _notes(root: Path, account: dict, sites: list[dict], warnings: list[str]) -> None:
    """What the archive carries that the import leaves out, counted for the summary."""
    mailboxes = 0
    mail = root / "homedir" / "mail"
    if mail.is_dir():
        for domain_dir in mail.iterdir():
            if domain_dir.is_dir() and not domain_dir.name.startswith(".") and da_import._normalize_domain(domain_dir.name):
                mailboxes += sum(1 for box in domain_dir.iterdir() if box.is_dir())
    if mailboxes:
        warnings.append(f"{mailboxes} mailbox(es) are not imported; create them again under Email")
    cron = root / "cron" / account["user"]
    if cron.is_file():
        jobs = [line for line in cron.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
                and re.match(r"^\s*(@\w+|\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+\S", line)]
        if jobs:
            warnings.append(f"{len(jobs)} cron job(s) are not imported; add them again under Cron")
    zones = root / "dnszones"
    if zones.is_dir():
        count = sum(1 for path in zones.iterdir() if path.is_file() and path.name.endswith(".db"))
        if count:
            warnings.append(f"{count} DNS zone(s) are not imported; with DNS Manager on, each website gets a zone of its own")
    for entry in sites:
        version = re.match(r"^(?:ea-php|alt-php)(\d)(\d)$", entry.get("phpversion") or "")
        if version:
            wanted = f"{version.group(1)}.{version.group(2)}"
            if wanted != da_import.DEFAULT_PHP_VERSION:
                warnings.append(
                    f"{entry['domain']} ran PHP {wanted} on cPanel and runs {da_import.DEFAULT_PHP_VERSION} here; "
                    "change it on the website's page if it needs the old one")


def _lay_out(archive: Path, stage_dir: Path) -> tuple[Path, list[str]]:
    """da_import.import_laid_out's lay_out for a cPanel archive. Everything
    happens under the importer's own stage folder, which is where the helper
    copies site files from (OPanel found its own cPanel import refused by the
    helper for staging anywhere else, .41, 2026-10-18)."""
    warnings: list[str] = []
    extracted = stage_dir / "archive"
    _log(f"Extracting {archive.name} ...")
    da_import._safe_extract_tar(archive, extracted)
    root = _find_root(extracted)
    account = _account(root, archive.name)
    sites, parked, homedir = _websites(root, account, warnings)
    target = stage_dir / "directadmin"
    _layout(root, target, account, sites, parked, homedir, warnings)
    _notes(root, account, sites, warnings)
    # What was not moved over (mail, logs, the rest of the home folder) is
    # disk nobody needs any more; the import proper starts with it gone.
    shutil.rmtree(extracted, ignore_errors=True)
    return target, warnings


# --- the import ----------------------------------------------------------------------

def import_cpanel_backup(archive_path: str, force: bool = False, replace_own: bool = False) -> dict:
    """Import one cPanel archive: the account, its websites, databases,
    aliases and certificates. Same flags and result as da_import.import_da_backup."""
    path = resolve_path(archive_path)
    _log(f"Starting cPanel import: {path.name}")
    return da_import.import_laid_out(path, _lay_out, force=force, replace_own=replace_own, source="cPanel")
