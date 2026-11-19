"""A restored site has to answer HTTPS without anyone re-issuing a certificate.

BPanel's account archive carried no certificates at all, and its restore
ignored the ones OPanel's archives carry - so every site came back on plain
HTTP, whichever panel the account came from. The box being restored onto has
no certbot account or renewal config for the domain, and usually no DNS
pointing at it yet, so "issue a new one" is not something the restore can fall
back on. The certificate travels inside the archive, in OPanel's format key for
key, so either panel restores the other's archive.
"""
import datetime as dt
import inspect
import json
import tarfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import maintenance
from app.core.database import Base
from app.models.entities import User, Website
from app.services import backup, mail, nginx, site_users, waf, wordpress
from app.services import ssl as ssl_service

OPANEL_SSL_KEYS = {"issued_as", "wildcard", "member_cert", "member_key", "member_ca"}


def make_cert(*names, days=60):
    """A real key pair, so the key/cert pairing check is actually exercised."""
    names = names or ("shop.test",)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=90))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name) for name in names]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Stand in for /etc/bpanel/sni (the panel-readable copy of every
    certificate) and /etc/nginx/bpanel/ssl/sites (uploaded certificates)."""
    store = tmp_path / "sni"
    uploaded = tmp_path / "uploaded"
    store.mkdir()
    uploaded.mkdir()
    monkeypatch.setattr(ssl_service, "PANEL_CERT_STORE", store)
    monkeypatch.setattr(ssl_service, "MANUAL_SSL_ROOT", uploaded)
    refreshes = []
    monkeypatch.setattr(ssl_service, "refresh_cert_store", lambda: refreshes.append(1))
    return SimpleNamespace(store=store, uploaded=uploaded, refreshes=refreshes)


def _put(folder: Path, files: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_bytes(content)
    return folder


@pytest.fixture
def account(tmp_path, monkeypatch):
    """alice, one account, and the parts of a backup that are not this test's."""
    db = _session()
    alice = User(username="alice", email="alice@example.test", role="end_user", is_active=True,
                 hashed_password="x", token_version=0)
    db.add(alice)
    db.commit()
    monkeypatch.setattr(backup.settings, "backup_root", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "_ensure_user_dir", lambda path: (path.mkdir(parents=True, exist_ok=True), path)[1])
    monkeypatch.setattr(backup, "_collect_applications", lambda user, db, tmp_dir: [])
    monkeypatch.setattr(mail, "backup_manifest", lambda db, user: {})

    def add_site(domain, **ssl):
        root = tmp_path / "home" / "alice" / domain
        (root / "public_html").mkdir(parents=True)
        (root / "public_html" / "index.php").write_text("<?php echo 1;", encoding="utf-8")
        site = Website(domain=domain, owner_id=alice.id, root_path=str(root), linux_user="alice",
                       php_version="8.3", app_type="php", status="active", **ssl)
        db.add(site)
        db.commit()
        return site

    def run(skipped=None):
        archive = backup.create_user_backup(alice, db, skipped=skipped if skipped is not None else [])
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            manifest = json.loads(tar.extractfile(backup.BACKUP_MANIFEST).read().decode("utf-8"))
        return archive, names, manifest

    yield SimpleNamespace(db=db, user=alice, add_site=add_site, run=run)
    db.close()


# --- the backup ---------------------------------------------------------------


def test_a_lets_encrypt_cert_is_taken_from_the_panel_readable_store_in_opanels_format(account, stores):
    cert, key = make_cert("shop.test", "www.shop.test")
    _put(stores.store / "shop.test", {"fullchain.pem": cert, "privkey.pem": key})
    account.add_site("shop.test", ssl_enabled=True, ssl_mode="letsencrypt")

    _, names, manifest = account.run()

    entry = manifest["websites"][0]["ssl"]
    assert set(entry) == OPANEL_SSL_KEYS, "the same keys OPanel writes, no more and no fewer"
    assert entry == {
        "issued_as": "letsencrypt",
        "wildcard": False,
        "member_cert": "ssl/shop.test/fullchain.pem",
        "member_key": "ssl/shop.test/privkey.pem",
        "member_ca": "",
    }
    assert "ssl/shop.test/fullchain.pem" in names and "ssl/shop.test/privkey.pem" in names
    assert stores.refreshes == [], "nothing to refresh when the copy is there"


def test_the_private_key_is_stored_unreadable_to_others(account, stores):
    cert, key = make_cert()
    _put(stores.store / "shop.test", {"fullchain.pem": cert, "privkey.pem": key})
    account.add_site("shop.test", ssl_enabled=True, ssl_mode="letsencrypt")

    archive, _, _ = account.run()

    with tarfile.open(archive) as tar:
        member = tar.getmember("ssl/shop.test/privkey.pem")
        assert member.mode == 0o600
        assert tar.extractfile(member).read() == key
        assert tar.getmember("ssl/shop.test/fullchain.pem").mode == 0o600


def test_an_uploaded_cert_is_taken_from_its_own_paths_with_its_chain(account, stores):
    cert, key = make_cert()
    chain, _ = make_cert("ca.example")
    own = _put(stores.uploaded / "shop.test", {"cert.crt": cert, "privkey.key": key, "ca.crt": chain})
    account.add_site("shop.test", ssl_enabled=True, ssl_mode="manual", ssl_cert_path=str(own / "cert.crt"),
                     ssl_key_path=str(own / "privkey.key"), ssl_ca_path=str(own / "ca.crt"))

    archive, names, manifest = account.run()

    entry = manifest["websites"][0]["ssl"]
    assert entry["issued_as"] == "manual" and entry["member_ca"] == "ssl/shop.test/ca.pem"
    with tarfile.open(archive) as tar:
        assert tar.extractfile("ssl/shop.test/fullchain.pem").read() == cert
        assert tar.extractfile("ssl/shop.test/ca.pem").read() == chain


def test_a_row_naming_a_file_outside_the_certificate_folders_is_never_packed(account, stores, tmp_path):
    """The row is all the backup goes on, and the archive leaves the box."""
    secret = _put(tmp_path / "opt", {"env": b"SECRET_KEY=do-not-ship\n"})
    account.add_site("shop.test", ssl_enabled=True, ssl_mode="manual",
                     ssl_cert_path=str(secret / "env"), ssl_key_path=str(secret / "env"))
    skipped = []

    archive, names, manifest = account.run(skipped)

    assert manifest["websites"][0]["ssl"] is None
    assert not any(name.startswith("ssl/") for name in names)
    assert b"do-not-ship" not in Path(archive).read_bytes()
    assert skipped[0]["path"] == "ssl:shop.test"


def test_a_cloudflare_wildcard_travels_as_opanels_dns01_wildcard(account, stores):
    cert, key = make_cert("shop.test", "*.shop.test")
    _put(stores.store / "shop.test", {"fullchain.pem": cert, "privkey.pem": key})
    account.add_site("api.shop.test", ssl_enabled=True, ssl_mode="cloudflare", ssl_source_domain="shop.test")

    archive, _, manifest = account.run()

    entry = manifest["websites"][0]["ssl"]
    assert entry["issued_as"] == "letsencrypt" and entry["wildcard"] is True
    assert entry["member_cert"] == "ssl/api.shop.test/fullchain.pem", "filed under the site, not the zone"
    with tarfile.open(archive) as tar:
        assert tar.extractfile("ssl/api.shop.test/privkey.pem").read() == key


def test_a_shared_cert_is_read_the_way_its_vhost_points_at_it(account, stores):
    """api/websites._borrowed_ssl_paths prefers the source's uploaded files."""
    uploaded, uploaded_key = make_cert("shop.test", "blog.test")
    stale, stale_key = make_cert("shop.test")
    _put(stores.uploaded / "shop.test", {"cert.crt": uploaded, "privkey.key": uploaded_key})
    _put(stores.store / "shop.test", {"fullchain.pem": stale, "privkey.pem": stale_key})
    account.add_site("blog.test", ssl_enabled=True, ssl_mode="shared", ssl_source_domain="shop.test")

    archive, _, manifest = account.run()

    assert manifest["websites"][0]["ssl"]["issued_as"] == "reuse"
    assert manifest["websites"][0]["ssl"]["wildcard"] is False
    with tarfile.open(archive) as tar:
        assert tar.extractfile("ssl/blog.test/fullchain.pem").read() == uploaded


def test_ssl_on_with_no_cert_on_disk_is_reported_after_one_refresh(account, stores):
    account.add_site("shop.test", ssl_enabled=True, ssl_mode="letsencrypt")
    account.add_site("blog.test", ssl_enabled=True, ssl_mode="letsencrypt")
    skipped = []

    _, names, manifest = account.run(skipped)

    assert [site["ssl"] for site in manifest["websites"]] == [None, None]
    assert [item["path"] for item in skipped] == ["ssl:shop.test", "ssl:blog.test"]
    assert stores.refreshes == [1], "the store is refreshed once per backup, not once per site"
    # The rest of the backup still happened.
    assert "sites/shop.test/site/public_html/index.php" in names


def test_a_cert_the_refresh_brings_in_is_packed(account, stores, monkeypatch):
    cert, key = make_cert()
    monkeypatch.setattr(ssl_service, "refresh_cert_store",
                        lambda: _put(stores.store / "shop.test", {"fullchain.pem": cert, "privkey.pem": key}))
    account.add_site("shop.test", ssl_enabled=True, ssl_mode="letsencrypt")

    _, names, manifest = account.run()

    assert manifest["websites"][0]["ssl"]["member_key"] == "ssl/shop.test/privkey.pem"
    assert "ssl/shop.test/privkey.pem" in names


def test_a_plain_http_site_carries_no_ssl_section(account, stores):
    cert, key = make_cert()
    _put(stores.store / "shop.test", {"fullchain.pem": cert, "privkey.pem": key})
    account.add_site("shop.test", ssl_enabled=False, ssl_mode="none")

    _, names, manifest = account.run()

    assert manifest["websites"][0]["ssl"] is None
    assert not any(name.startswith("ssl/") for name in names)
    assert stores.refreshes == []


# --- the restore --------------------------------------------------------------


def _member(tar, name, payload: bytes, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = mode
    tar.addfile(info, BytesIO(payload))


def _opanel_archive(path: Path, sites: list[dict], files: dict) -> Path:
    """An archive the way OPanel's create_user_backup writes one."""
    manifest = {
        "kind": "opanel_user",
        "version": 1,
        "user": {"username": "babatapapp", "email": "owner@example.test", "is_active": True,
                 "website_limit": 5, "storage_limit_mb": 0},
        "websites": sites,
        "databases": [],
    }
    with tarfile.open(path, "w:gz") as tar:
        _member(tar, backup.BACKUP_MANIFEST, json.dumps(manifest).encode("utf-8"))
        for site in sites:
            _member(tar, f"sites/{site['domain']}/site/public_html/index.php", b"<?php echo 1;")
        for name, payload in files.items():
            _member(tar, name, payload, mode=0o600)
    return path


def _opanel_site(domain, ssl=True, ca=False):
    base = f"ssl/{domain}"
    return {
        "domain": domain, "php_version": "8.3", "app_type": "php", "status": "active",
        "document_root": "public_html", "nginx_rewrite_mode": "none", "waf_enabled": False,
        "aliases": [], "database": None,
        "ssl": {"issued_as": "letsencrypt", "wildcard": False, "member_cert": f"{base}/fullchain.pem",
                "member_key": f"{base}/privkey.pem", "member_ca": f"{base}/ca.pem" if ca else ""} if ssl else None,
    }


@pytest.fixture
def restore_box(tmp_path, monkeypatch):
    """A fresh box to restore onto, recording what reaches disk and nginx."""
    db = _session()
    events = []
    ok = SimpleNamespace(returncode=0, stdout="", stderr="")

    def write_cert(domain, certificate, private_key, ca_bundle=b""):
        events.append(("install", domain))
        paths = ssl_service.manual_ssl_paths(domain)
        if not ca_bundle:
            paths["ca"] = None
        return paths

    def rewrite_vhost(domain, root_path, **kwargs):
        events.append(("vhost", domain, kwargs))
        return "/etc/nginx/sites-available/x.conf"

    monkeypatch.setattr(ssl_service, "_write_manual_ssl_files", write_cert)
    monkeypatch.setattr(ssl_service, "remove_manual_ssl", lambda domain: events.append(("remove", domain)))
    monkeypatch.setattr(nginx, "rewrite_vhost", rewrite_vhost)
    monkeypatch.setattr(nginx, "sync_http_flood_zones", lambda *a, **k: ok)
    monkeypatch.setattr(waf, "sync_website_rules", lambda website: ok)
    monkeypatch.setattr(wordpress, "fix_permissions", lambda *a, **k: None)
    monkeypatch.setattr(site_users, "IMPORT_STAGE_BASE", tmp_path / "stage")
    for name in ("ensure_panel_user", "ensure_site_runtime", "import_site_files", "ensure_document_root"):
        monkeypatch.setattr(site_users, name, lambda *a, **k: None)
    monkeypatch.setattr(backup, "hash_password", lambda value: "hashed")
    monkeypatch.setattr(mail, "restore_manifest", lambda *a, **k: [])
    monkeypatch.setattr(mail, "sync_quietly", lambda db: None)
    from app.services import dns
    monkeypatch.setattr(dns, "sync_quietly", lambda db: None)

    def restore(archive: Path):
        monkeypatch.setattr(backup, "user_backup_path", lambda name: archive)
        return backup.restore_user_backup(archive.name, db, operator_is_admin=True)

    yield SimpleNamespace(db=db, events=events, restore=restore)
    db.close()


def _vhost_call(events, domain):
    return next(event[2] for event in events if event[0] == "vhost" and event[1] == domain)


def test_an_opanel_archive_comes_back_on_https(tmp_path, restore_box):
    cert, key = make_cert("api.babatap.com")
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com")], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        "ssl/api.babatap.com/privkey.pem": key,
    })

    result = restore_box.restore(archive)

    site = restore_box.db.query(Website).filter(Website.domain == "api.babatap.com").one()
    assert site.ssl_enabled is True
    # Uploaded, whatever it was issued as: this box has no renewal config.
    assert site.ssl_mode == "manual"
    assert site.ssl_cert_path == "/etc/nginx/bpanel/ssl/sites/api.babatap.com/cert.crt"
    assert site.ssl_key_path == "/etc/nginx/bpanel/ssl/sites/api.babatap.com/privkey.key"
    vhost = _vhost_call(restore_box.events, "api.babatap.com")
    assert vhost["ssl_cert_path"] == site.ssl_cert_path and vhost["ssl_key_path"] == site.ssl_key_path
    kinds = [event[0] for event in restore_box.events]
    assert kinds.index("install") < kinds.index("vhost"), "the certificate is on disk before the vhost names it"
    assert result["ssl_warnings"] == []
    assert [(item["domain"], item["issued_as"], item["expired"]) for item in result["certificates"]] == [
        ("api.babatap.com", "letsencrypt", False)]
    assert result["certificates"][0]["expires"]


def test_a_bpanel_archive_restores_on_another_bpanel_with_its_certificates(account, stores, restore_box):
    cert, key = make_cert("shop.test", "www.shop.test")
    _put(stores.store / "shop.test", {"fullchain.pem": cert, "privkey.pem": key})
    account.add_site("shop.test", ssl_enabled=True, ssl_mode="letsencrypt")
    account.add_site("plain.test", ssl_enabled=False, ssl_mode="none")
    archive, _, _ = account.run()

    result = restore_box.restore(Path(archive))

    assert [item["domain"] for item in result["certificates"]] == ["shop.test"]
    restored = {site.domain: site for site in restore_box.db.query(Website).all()}
    assert restored["shop.test"].ssl_enabled is True and restored["shop.test"].ssl_mode == "manual"
    assert restored["plain.test"].ssl_enabled is False
    assert "ssl_cert_path" not in _vhost_call(restore_box.events, "plain.test")


def test_a_broken_certificate_is_a_warning_not_a_failed_restore(tmp_path, restore_box):
    cert, _ = make_cert("api.babatap.com")
    _, other_key = make_cert("api.babatap.com")
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com")], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        "ssl/api.babatap.com/privkey.pem": other_key,
    })

    result = restore_box.restore(archive)

    assert [item["domain"] for item in result["websites"]] == ["api.babatap.com"], "the site itself came back"
    assert result["certificates"] == []
    assert len(result["ssl_warnings"]) == 1 and result["ssl_warnings"][0].startswith("api.babatap.com: ")
    site = restore_box.db.query(Website).filter(Website.domain == "api.babatap.com").one()
    assert site.ssl_enabled is False and site.ssl_mode == "none"
    assert "ssl_cert_path" not in _vhost_call(restore_box.events, "api.babatap.com")
    assert not any(event[0] == "install" for event in restore_box.events)


def test_an_expired_certificate_is_still_put_back(tmp_path, restore_box):
    """Refusing it would leave the site on plain HTTP; it still describes what
    the site was serving, and Let's Encrypt can take over after."""
    cert, key = make_cert("api.babatap.com", days=-1)
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com")], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        "ssl/api.babatap.com/privkey.pem": key,
    })

    result = restore_box.restore(archive)

    assert result["certificates"][0]["expired"] is True
    assert result["ssl_warnings"] == []


@pytest.mark.parametrize("member_key", [
    "ssl/other.test/privkey.pem",        # another site's folder
    "sites/api.babatap.com/site/key",    # anywhere else in the archive
    "ssl/api.babatap.com/../x/key.pem",  # out of the folder
    "/etc/ssl/private/key.pem",
])
def test_an_entry_pointing_outside_its_own_ssl_folder_is_refused(tmp_path, restore_box, member_key):
    cert, key = make_cert("api.babatap.com")
    site = _opanel_site("api.babatap.com")
    site["ssl"]["member_key"] = member_key
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [site], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        member_key.lstrip("/"): key,
    })

    result = restore_box.restore(archive)

    assert result["certificates"] == []
    assert "Invalid certificate member" in result["ssl_warnings"][0]
    assert not any(event[0] == "install" for event in restore_box.events)


def test_a_certificate_for_another_domain_is_not_installed(tmp_path, restore_box):
    """Every uploaded certificate is also served on :2222 by the names inside it."""
    cert, key = make_cert("bank.example", "panel.example")
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com")], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        "ssl/api.babatap.com/privkey.pem": key,
    })

    result = restore_box.restore(archive)

    assert result["certificates"] == [] and "does not match" in result["ssl_warnings"][0]
    assert not any(event[0] == "install" for event in restore_box.events)


def test_a_certificate_for_the_panels_own_name_is_not_installed(tmp_path, restore_box, monkeypatch):
    monkeypatch.setattr(backup.settings, "panel_domain", "api.babatap.com")
    cert, key = make_cert("api.babatap.com")
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com")], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        "ssl/api.babatap.com/privkey.pem": key,
    })

    result = restore_box.restore(archive)

    assert result["certificates"] == [] and "panel" in result["ssl_warnings"][0]


def test_an_oversized_certificate_member_is_a_warning(tmp_path, restore_box):
    cert, _ = make_cert("api.babatap.com")
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com")], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        "ssl/api.babatap.com/privkey.pem": b"\0" * (backup.MAX_SSL_MEMBER_BYTES + 1),
    })

    result = restore_box.restore(archive)

    assert "Invalid certificate member" in result["ssl_warnings"][0]


def test_a_certificate_nginx_will_not_load_leaves_the_site_on_http(tmp_path, restore_box, monkeypatch):
    cert, key = make_cert("api.babatap.com")
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com")], {
        "ssl/api.babatap.com/fullchain.pem": cert,
        "ssl/api.babatap.com/privkey.pem": key,
    })
    calls = []

    def picky(domain, root_path, **kwargs):
        calls.append(kwargs)
        if kwargs.get("ssl_cert_path"):
            raise RuntimeError("nginx: [emerg] cannot load certificate")
        return "ok"

    monkeypatch.setattr(nginx, "rewrite_vhost", picky)

    result = restore_box.restore(archive)

    assert [bool(call.get("ssl_cert_path")) for call in calls] == [True, False]
    assert result["certificates"] == []
    assert "nginx would not load" in result["ssl_warnings"][0]
    assert ("remove", "api.babatap.com") in restore_box.events
    site = restore_box.db.query(Website).filter(Website.domain == "api.babatap.com").one()
    assert site.ssl_enabled is False and site.ssl_cert_path is None


def test_a_site_without_a_certificate_section_is_left_alone(tmp_path, restore_box):
    archive = _opanel_archive(tmp_path / "opanel.tar.gz", [_opanel_site("api.babatap.com", ssl=False)], {})

    result = restore_box.restore(archive)

    assert result["certificates"] == [] and result["ssl_warnings"] == []
    assert "ssl_cert_path" not in _vhost_call(restore_box.events, "api.babatap.com")


def test_a_site_that_already_has_its_own_certificate_here_keeps_it():
    """Restoring last night's backup over a live site must not swap a renewing
    Let's Encrypt lineage for a copy nothing renews."""
    source = inspect.getsource(backup.restore_user_backup)
    assert "keeps_own_certificate = not created_site and bool(website.ssl_enabled)" in source
    assert "if ssl_info and not keeps_own_certificate:" in source


def test_restore_installs_the_cert_before_it_writes_the_vhost():
    source = inspect.getsource(backup.restore_user_backup)
    assert source.index("_restore_site_certificate(") < source.index("nginx.rewrite_vhost(")
    assert "**ssl_kwargs" in source
    assert '"certificates": restored_certificates' in source
    assert '"ssl_warnings": ssl_warnings' in source


def test_certificate_members_are_read_in_one_pass(tmp_path):
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _member(tar, "ssl/x.test/fullchain.pem", b"cert")
        _member(tar, "ssl/x.test/privkey.pem", b"key")
        _member(tar, "ssl/y.test/privkey.pem", b"not wanted")
    members = backup._read_certificate_members(
        archive, {"ssl/x.test/fullchain.pem", "ssl/x.test/privkey.pem", "ssl/x.test/ca.pem"})
    assert members == {"ssl/x.test/fullchain.pem": b"cert", "ssl/x.test/privkey.pem": b"key"}
    assert backup._read_certificate_members(archive, set()) == {}


def test_an_archive_cannot_make_the_restore_hold_unbounded_key_material(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "MAX_SSL_MEMBERS_TOTAL_BYTES", 6)
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _member(tar, "ssl/x.test/fullchain.pem", b"cert")
        _member(tar, "ssl/x.test/privkey.pem", b"key")
    members = backup._read_certificate_members(archive, {"ssl/x.test/fullchain.pem", "ssl/x.test/privkey.pem"})
    assert members == {"ssl/x.test/fullchain.pem": b"cert", "ssl/x.test/privkey.pem": None}


# --- the pieces ---------------------------------------------------------------


def test_installing_refuses_a_key_that_does_not_match(monkeypatch):
    cert, _ = make_cert()
    _, other_key = make_cert()
    monkeypatch.setattr(ssl_service, "_write_manual_ssl_files", lambda *a, **k: pytest.fail("wrote a broken pair"))
    with pytest.raises(ValueError, match="does not match"):
        ssl_service.install_site_certificate("shop.test", cert, other_key)


def test_a_wildcard_installs_for_a_name_it_covers(monkeypatch):
    cert, key = make_cert("shop.test", "*.shop.test")
    written = {}
    monkeypatch.setattr(ssl_service, "_write_manual_ssl_files",
                        lambda domain, c, k, ca=b"": written.update(domain=domain) or {"cert": "c", "key": "k", "ca": None})
    assert ssl_service.install_site_certificate("api.shop.test", cert, key)["cert"] == "c"
    assert written["domain"] == "api.shop.test"


def test_the_restore_note_reads_like_opanels():
    note = maintenance._panel_restore_note({
        "websites": [{"domain": "a.test"}, {"domain": "b.test"}],
        "certificates": [{"domain": "a.test"}],
        "ssl_warnings": ["b.test: certificate material missing from the archive"],
    })
    assert note == "2 site(s), 1 cert(s), SSL not restored for 1: b.test: certificate material missing from the archive"
    assert maintenance._panel_restore_note({"websites": []}) == "0 site(s)"
