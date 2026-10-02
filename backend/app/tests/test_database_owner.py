"""Databases change hands with their website, and an admin can assign one.

On 160.236.192.120 the website reviewthammy.vn and the app behind it moved to
the customer wow while the app's database, named only in the app's .env,
stayed with admin: the customer could not see, back up or manage their own
site's data (2026-10-02).
"""
import inspect

import pytest
from fastapi import HTTPException

from app.api import databases as databases_api
from app.api import websites as websites_api
from app.core.permissions import Role
from app.models.entities import DatabaseAccount, SiteApp, User, Website


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *conditions):
        rows = self.rows
        for condition in conditions:
            column = getattr(condition.left, "key", None)
            value = getattr(condition.right, "value", None)
            if column is None:
                continue
            if type(condition).__name__ == "BinaryExpression" and condition.operator.__name__ == "is_":
                rows = [row for row in rows if getattr(row, column) is None]
            else:
                rows = [row for row in rows if getattr(row, column) == value]
        return _Query(rows)

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, **tables):
        self.tables = tables
        self.commits = 0

    def query(self, model):
        return _Query(self.tables.get(model.__name__, []))

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        pass


def _world(env=""):
    admin = User(id=1, username="admin", email="a@example.test", role=str(Role.admin))
    wow = User(id=2, username="wow", email="w@example.test", role="end_user")
    app = SiteApp(id=1, owner_id=1, name="reviewthammy", kind="node", env=env)
    app.owner = admin
    site = Website(id=7, domain="reviewthammy.vn", owner_id=1, app_id=1, root_path="/home/admin/reviewthammy.vn")
    linked = DatabaseAccount(id=1, owner_id=1, website_id=7, db_name="site_db", db_user="u1", db_password="x")
    used = DatabaseAccount(id=2, owner_id=1, website_id=None, db_name="reviewthammy", db_user="u2", db_password="x")
    unrelated = DatabaseAccount(id=3, owner_id=1, website_id=None, db_name="review", db_user="u3", db_password="x")
    other_site = DatabaseAccount(id=4, owner_id=1, website_id=99, db_name="reviewthammy_old", db_user="u4", db_password="x")
    db = _Db(User=[admin, wow], SiteApp=[app], Website=[site],
             DatabaseAccount=[linked, used, unrelated, other_site])
    return db, admin, wow, app, site, linked, used


def test_the_websites_databases_and_the_ones_its_app_names_move_with_it(monkeypatch):
    db, admin, wow, app, site, linked, used = _world()
    # The app's DATABASE_URL lives in its own .env, as on .120.
    monkeypatch.setattr(websites_api.file_manager, "read_text_file",
                        lambda target, path, allow_sensitive=False: "DATABASE_URL=mysql://u2:pw@localhost:3306/reviewthammy\n")
    own, app_dbs = websites_api._databases_moving_with(db, site)
    assert own == [linked]
    # By whole name only: "review" is a different database, and one linked to
    # another website stays with that website.
    assert [item.db_name for item in app_dbs] == ["reviewthammy"]


def test_the_panels_own_app_environment_counts_too(monkeypatch):
    db, *_rest = _world(env="DB_DATABASE=reviewthammy")
    site = db.tables["Website"][0]

    def missing(*args, **kwargs):
        raise ValueError("File not found")

    monkeypatch.setattr(websites_api.file_manager, "read_text_file", missing)
    _own, app_dbs = websites_api._databases_moving_with(db, site)
    assert [item.db_name for item in app_dbs] == ["reviewthammy"]


def test_a_website_without_an_app_takes_only_its_own():
    db, admin, wow, app, site, linked, used = _world()
    site.app_id = None
    own, app_dbs = websites_api._databases_moving_with(db, site)
    assert own == [linked] and app_dbs == []


def test_assigning_a_website_moves_its_databases_and_the_apps():
    source = inspect.getsource(websites_api.update_website)
    assert "own_databases, app_databases = _databases_moving_with(db, website)" in source
    assert source.index("_databases_moving_with(db, website)") < source.index("move_site_runtime")
    assert "for item in own_databases + app_databases:" in source
    # An app that could not move keeps its databases; the website's own go with the website.
    failed = source.split("except (RuntimeError, ValueError) as exc:\n                    # The website has moved", 1)[1]
    assert "for item in own_databases:" in failed.split("raise HTTPException", 1)[0]


def test_an_admin_assigns_a_database_and_only_an_admin(monkeypatch):
    db, admin, wow, app, site, linked, used = _world()
    logged = []
    monkeypatch.setattr(databases_api, "log_action", lambda *args, **kwargs: logged.append(args))
    payload = databases_api.DatabaseOwnerUpdate(owner_id=2)

    with pytest.raises(HTTPException) as exc:
        databases_api.assign_database(2, payload, None, db=db, current_user=wow)
    assert exc.value.status_code == 403

    used.owner = admin
    item = databases_api.assign_database(2, payload, None, db=db, current_user=admin)
    assert item.owner_id == 2 and db.commits == 1
    assert logged and logged[0][2] == "assign_database" and "admin -> wow" in logged[0][4]


def test_a_database_that_belongs_to_a_website_goes_with_the_website():
    db, admin, wow, app, site, linked, used = _world()
    with pytest.raises(HTTPException) as exc:
        databases_api.assign_database(1, databases_api.DatabaseOwnerUpdate(owner_id=2), None,
                                      db=db, current_user=admin)
    assert exc.value.status_code == 409 and "reviewthammy.vn" in exc.value.detail
    assert linked.owner_id == 1


def test_the_assign_form_is_told_what_moves(monkeypatch):
    db, admin, wow, app, site, linked, used = _world()
    monkeypatch.setattr(websites_api.file_manager, "read_text_file",
                        lambda target, path, allow_sensitive=False: "DATABASE_URL=mysql://x@y/reviewthammy")
    preview = websites_api.website_transfer_preview(7, db=db, current_user=admin)
    assert preview == {"application": "reviewthammy", "databases": ["site_db", "reviewthammy"]}
    with pytest.raises(HTTPException):
        websites_api.website_transfer_preview(7, db=db, current_user=wow)
