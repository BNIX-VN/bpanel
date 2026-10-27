"""Import accounts pulled off a FastPanel server (the FastPanel Import addon,
operator 2026-10-27 - as OPanel's, whose fastpanel_import.py this follows).

FastPanel's own backups keep a site's files and its databases in separate
archives, so there is nothing to upload: the panel signs in to the FastPanel
server as root (services/migrate_ssh.py) and packs each account picked into
one archive, ``fastpanel-<user>.tar.gz``, laid out the way a DirectAdmin
backup is:

- ``backup/user.conf`` and ``backup/domains.list``: the account and its sites;
- ``domains/<domain>/public_html``: each site's files, from
  ``/var/www/<user>/data/www/<domain>``;
- ``mysql/<db>.sql``: the databases its sites' configs name, and those named
  after the account;
- ``backup/<domain>/domain.{cert,key}``: the certificate nginx serves it with;
- ``bpanel/aliases.tsv``: each site's other names (nginx ``server_name``).

The aliases become each domain's DirectAdmin pointers before the DirectAdmin
importer (da_import.import_laid_out) runs, so they land in the vhost and on
the certificate like any DirectAdmin pointer.

Written from OPanel's code and FastPanel 2's documented layout; it has not
been run against a live FastPanel server yet.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.services import da_import

BACKUP_DIR = Path(os.environ.get("BPANEL_FASTPANEL_BACKUP_DIR", "/home/admin/bpanel_backups/fastpanel"))
BACKUP_DIR_IS_DEFAULT = "BPANEL_FASTPANEL_BACKUP_DIR" not in os.environ
NAME_RE = re.compile(r"^fastpanel-(?P<user>[a-z][a-z0-9_-]{0,31})\.tar\.gz$")


def _base(name: str) -> str:
    return (name or "").replace("\\", "/").rsplit("/", 1)[-1]


def is_fastpanel_name(name: str) -> bool:
    return bool(NAME_RE.match(_base(name)))


def account_of(name: str) -> str:
    match = NAME_RE.match(_base(name))
    return match.group("user") if match else ""


def ensure_backup_dir() -> None:
    da_import.ensure_import_dir(BACKUP_DIR, BACKUP_DIR_IS_DEFAULT)


def resolve_path(archive_path: str) -> Path:
    """A packed FastPanel account inside BACKUP_DIR, and nothing else."""
    raw = (archive_path or "").strip()
    if not raw:
        raise FileNotFoundError("Backup not found")
    folder = BACKUP_DIR.resolve()
    candidate = Path(raw)
    path = (candidate if candidate.is_absolute() else folder / candidate.name).resolve()
    if path.parent != folder or not path.is_file() or not is_fastpanel_name(path.name):
        raise FileNotFoundError("Backup not found")
    return path


def _aliases(root: Path) -> dict[str, list[str]]:
    """Each site's other names, from the packed nginx server_name lines."""
    found: dict[str, list[str]] = {}
    table = root / "bpanel" / "aliases.tsv"
    if not table.is_file():
        return found
    for line in table.read_text(encoding="utf-8", errors="ignore").splitlines():
        domain, _, names = line.partition("\t")
        domain = da_import._normalize_domain(domain) or ""
        if not domain:
            continue
        others = []
        for name in names.split():
            name = da_import._normalize_domain(name.strip())
            # www.<domain> is served by every website here already.
            if name and name != domain and name != f"www.{domain}" and name not in others:
                others.append(name)
        found[domain] = others
    return found


def _lay_out(archive: Path, stage_dir: Path) -> tuple[Path, list[str]]:
    """da_import.import_laid_out's lay_out for a packed FastPanel account:
    already the DirectAdmin layout, but for the aliases, which become each
    domain's pointers - unless they are a site of the same account."""
    root = stage_dir / "extracted"
    da_import._log(f"[fastpanel] Extracting {archive.name} ...")
    da_import._safe_extract_tar(archive, root)
    sites = set(da_import._discover_domains(root))
    for domain, names in _aliases(root).items():
        names = [name for name in names if name not in sites]
        if domain in sites and names:
            (root / "backup" / f"{domain}.pointers").write_text(
                "".join(f"{name}=alias\n" for name in names), encoding="utf-8")
    return root, []


def import_fastpanel_backup(archive_path: str, force: bool = False, replace_own: bool = False) -> dict:
    """Import one packed FastPanel account. Same flags and result as
    da_import.import_da_backup."""
    path = resolve_path(archive_path)
    da_import._log(f"[fastpanel] Starting FastPanel import: {path.name}")
    return da_import.import_laid_out(path, _lay_out, force=force, replace_own=replace_own, source="FastPanel")
