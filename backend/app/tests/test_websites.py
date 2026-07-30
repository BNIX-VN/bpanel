from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import websites
from app.core.database import Base
from app.models.entities import User, Website, WebsiteAlias


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
