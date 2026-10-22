import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import websites
from app.core.database import Base
from app.models.entities import User, Website, WebsiteAlias
from app.schemas.schemas import WebsiteCreate


def _db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_websites(db):
    admin = User(id=1, username="admin", email="admin@example.test", hashed_password="x", role="admin")
    user = User(id=2, username="client", email="client@example.test", hashed_password="x", role="end_user")
    owned = Website(
        id=1,
        domain="client-site.test",
        owner_id=2,
        root_path="/home/client/client-site.test",
        linux_user="client",
    )
    other = Website(
        id=2,
        domain="other-site.test",
        owner_id=1,
        root_path="/home/admin/other-site.test",
        linux_user="admin",
    )
    alias = WebsiteAlias(id=1, website_id=1, domain="shop.client-site.test", mode="alias")
    db.add_all([admin, user, owned, other, alias])
    db.commit()
    return admin, user


def test_list_websites_filters_by_alias_for_admin(monkeypatch):
    db = _db_session()
    admin, _ = _seed_websites(db)
    monkeypatch.setattr(websites, "_sync_live_ssl_flags", lambda _db, rows: rows)

    rows = websites.list_websites(q="shop.client", db=db, current_user=admin)

    assert [row.domain for row in rows] == ["client-site.test"]


def test_list_websites_search_keeps_user_scope(monkeypatch):
    db = _db_session()
    _, user = _seed_websites(db)
    monkeypatch.setattr(websites, "_sync_live_ssl_flags", lambda _db, rows: rows)

    rows = websites.list_websites(q="other", db=db, current_user=user)

    assert rows == []


def test_create_website_rejects_a_domain_already_in_the_table(monkeypatch):
    db = _db_session()
    admin, _ = _seed_websites(db)
    monkeypatch.setattr(websites.nginx, "vhost_exists", lambda domain: False)

    with pytest.raises(Exception) as exc:
        websites.create_website(
            WebsiteCreate(domain="client-site.test", install_wordpress=False, app_type="php"),
            request=None, db=db, current_user=admin,
        )
    assert getattr(exc.value, "status_code", None) == 409


def test_create_website_rejects_a_domain_with_a_leftover_nginx_config(monkeypatch):
    db = _db_session()
    admin, _ = _seed_websites(db)
    # Not in the websites table, but a config file is still on disk.
    monkeypatch.setattr(websites.nginx, "vhost_exists", lambda domain: domain == "ghost.test")

    with pytest.raises(Exception) as exc:
        websites.create_website(
            WebsiteCreate(domain="ghost.test", install_wordpress=False, app_type="php"),
            request=None, db=db, current_user=admin,
        )
    assert getattr(exc.value, "status_code", None) == 409


def test_a_wordpress_site_made_without_installing_stays_wordpress(monkeypatch, tmp_path):
    """Mode WordPress, "Install WordPress" unticked: the owner uploads WordPress
    themselves. The site was turned into "php" with no front controller, so
    every permalink of the uploaded site answered 404 (operator, 2026-10-22)."""
    db = _db_session()
    admin, _ = _seed_websites(db)
    vhosts = []
    monkeypatch.setattr(websites.nginx, "vhost_exists", lambda domain: False)
    monkeypatch.setattr(websites.nginx, "write_vhost", lambda domain, root, **kw: vhosts.append(kw))
    monkeypatch.setattr(websites.site_users, "ensure_site_runtime", lambda domain, root, php, user: user)
    monkeypatch.setattr(websites.site_users, "document_root", lambda root: tmp_path)
    monkeypatch.setattr(websites.site_users, "fix_site_path", lambda *a, **k: None)
    monkeypatch.setattr(websites.site_users, "site_php_fpm_socket", lambda *a, **k: "/run/php/test.sock")
    monkeypatch.setattr(websites, "_write_placeholder_page", lambda *a, **k: None)
    monkeypatch.setattr(websites, "_ensure_default_waf_file", lambda *a, **k: None)
    monkeypatch.setattr(websites.storage_quota, "enforce_user_storage_quota", lambda *a, **k: None)
    monkeypatch.setattr(websites.dns, "zone_for_new_website", lambda *a, **k: None)
    monkeypatch.setattr(websites, "log_action", lambda *a, **k: None)

    site = websites.create_website(
        WebsiteCreate(domain="upload.test", install_wordpress=False, app_type="wordpress"),
        request=None, db=db, current_user=admin,
    )

    assert site.app_type == "wordpress"
    assert site.nginx_rewrite_mode == "front_controller"
    assert vhosts and vhosts[-1]["app_type"] == "wordpress"
    assert vhosts[-1]["rewrite_mode"] == "front_controller"
