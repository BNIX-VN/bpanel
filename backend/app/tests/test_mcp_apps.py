"""MCP's file tools work in an application's folder (operator, 2026-11-07).

An application's code lives in ~/apps/<name>, outside every website, and the
file tools only took a domain: a customer uploading an Astro app's source with
their token had nowhere to put it but a website folder.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import maintenance as maintenance_api
from app.core.database import Base
from app.models.entities import McpToken, SiteApp, User, Website
from app.services import mcp, mcp_tools


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    people = {}
    for name, role in (("admin", "admin"), ("alice", "end_user"), ("bob", "end_user")):
        people[name] = User(username=name, email=f"{name}@example.test", role=role, is_active=True,
                            hashed_password="x", token_version=0)
        db.add(people[name])
    db.commit()
    db.add(SiteApp(owner_id=people["alice"].id, name="astro", kind="node", port=21001))
    db.add(Website(domain="alice.test", owner_id=people["alice"].id, root_path="/home/alice/alice.test",
                   linux_user="alice"))
    db.commit()
    calls = []
    monkeypatch.setattr(maintenance_api, "write_file", lambda payload, db, current_user: calls.append(payload) or {"ok": True})
    monkeypatch.setattr(maintenance_api, "delete_entries", lambda payload, db, current_user: calls.append(payload) or {"ok": True})
    monkeypatch.setattr(maintenance_api, "make_directory", lambda payload, db, current_user: calls.append(payload) or {"ok": True})

    def ctx(name):
        user = people[name]
        token = McpToken(id=1, user_id=user.id, name="t", token_hash="h", prefix="bpmcp_x", can_write=True,
                         expires_at=datetime.utcnow() + timedelta(days=1), created_at=datetime.utcnow())
        return mcp.Context(db=db, user=user, token=token)

    yield ctx, calls, db
    db.close()


def _call(ctx, tool, args):
    spec = mcp.REGISTRY[tool]
    return spec.handler(ctx, mcp.validate_arguments(spec, args))


def test_the_owner_writes_into_their_app_by_name(env):
    ctx, calls, db = env
    _call(ctx("alice"), "write_file", {"app": "astro", "path": "src/index.astro", "content": "hi"})
    app = db.query(SiteApp).filter(SiteApp.name == "astro").one()
    assert calls[-1].app_id == app.id and calls[-1].website_id is None
    _call(ctx("alice"), "create_directory", {"app": "astro", "name": "public"})
    assert calls[-1].path == "", "an app's directories start at its root, not public_html"


def test_another_customer_cannot_reach_it(env):
    ctx, calls, _ = env
    with pytest.raises(mcp.ToolError, match="No application named astro"):
        _call(ctx("bob"), "write_file", {"app": "astro", "path": "x", "content": "y"})
    assert calls == []


def test_one_tree_at_a_time(env):
    ctx, _, _ = env
    for args in ({"path": "x", "content": "y"},
                 {"app": "astro", "domain": "alice.test", "path": "x", "content": "y"}):
        with pytest.raises(mcp.ToolError, match="not both"):
            _call(ctx("alice"), "write_file", args)


def test_the_website_way_still_works(env):
    ctx, calls, db = env
    _call(ctx("alice"), "write_file", {"domain": "alice.test", "path": "a.txt", "content": "b"})
    site = db.query(Website).filter(Website.domain == "alice.test").one()
    assert calls[-1].website_id == site.id and calls[-1].app_id is None


def test_the_app_root_itself_is_never_deleted(env):
    ctx, calls, _ = env
    for path in ("/", "."):
        with pytest.raises(mcp.ToolError, match="the application"):
            _call(ctx("alice"), "delete_file", {"app": "astro", "path": path})
    with pytest.raises(mcp.ToolError):                       # refused as missing
        _call(ctx("alice"), "delete_file", {"app": "astro", "path": ""})
    assert calls == []


def test_list_apps_shows_only_what_the_token_can_reach(env):
    ctx, _, _ = env
    assert [row["name"] for row in _call(ctx("alice"), "list_apps", {})] == ["astro"]
    assert _call(ctx("bob"), "list_apps", {}) == []
    assert [row["owner"] for row in _call(ctx("admin"), "list_apps", {})] == ["alice"]
