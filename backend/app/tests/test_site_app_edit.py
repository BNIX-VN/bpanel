"""Edit changes every setting of an application (operator, 2026-11-08).

It used to offer only the environment, port, memory and a container's CPU.
Name, start command, Node version, image, container port and start-on-boot are
editable too; a compose application keeps its name, because its project and
volumes are called after it and the rename's teardown would drop them.
"""
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import site_apps as api
from app.core.database import Base
from app.models.entities import SiteApp, User
from app.schemas.schemas import SiteAppUpdate

APP_JSX = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    alice = User(username="alice", email="alice@example.test", role="end_user", is_active=True,
                 hashed_password="x", token_version=0, node_apps_limit=3)
    db.add(alice)
    db.commit()
    node = SiteApp(owner_id=alice.id, name="web", kind="node", port=21001, start_kind="npm", start_arg="start",
                   node_major="22", memory_limit_mb=256)
    stack = SiteApp(owner_id=alice.id, name="stack", kind="compose", port=21002, memory_limit_mb=256,
                    compose_source="services: {}", web_service="app")
    db.add_all([node, stack])
    db.commit()
    calls = []
    deployed = {"yes": True}
    monkeypatch.setattr(api, "_deployed", lambda app, name=None: deployed["yes"])
    monkeypatch.setattr(api.site_apps, "control", lambda app, action: calls.append(("control", app.name, action)) or "")
    monkeypatch.setattr(api.site_apps, "write_runtime", lambda app: calls.append(("write", app.name, app.start_kind, app.start_arg, app.node_major)) or "")
    monkeypatch.setattr(api.site_apps, "fetch_images", lambda app: "")
    monkeypatch.setattr(api.site_apps, "delete_runtime", lambda app, name=None: calls.append(("delete", name)))
    monkeypatch.setattr(api.site_apps, "rename_directory", lambda app, old: calls.append(("rename", old, app.name)) or "")
    monkeypatch.setattr(api.site_apps, "settled_state", lambda app: "active")
    monkeypatch.setattr(api, "log_action", lambda *a, **k: None)
    yield db, alice, node, stack, calls, deployed
    db.close()


def _save(env, app, **fields):
    db, alice, *_ = env
    return api.update_site_app(app.id, SiteAppUpdate(**fields), db=db, current_user=alice)


def test_the_start_command_and_node_version_are_rewritten_into_the_unit(env):
    *_, node, _, calls, _ = env
    _save(env, node, start_kind="node", start_arg="server.js", node_major="20")
    assert ("write", "web", "node", "server.js", "20") in calls
    assert ("control", "web", "restart") in calls


def test_a_rename_moves_the_folder_and_enables_the_new_unit(env):
    *_, node, _, calls, _ = env
    out = _save(env, node, name="shop")
    assert out["name"] == "shop"
    assert ("rename", "web", "shop") in calls and ("delete", "web") in calls
    assert calls.index(("control", "shop", "enable")) < calls.index(("control", "shop", "restart"))


def test_a_compose_app_is_never_renamed(env):
    *_, stack, calls, _ = env
    with pytest.raises(HTTPException) as err:
        _save(env, stack, name="other")
    assert err.value.status_code == 400 and "volumes" in err.value.detail
    assert calls == [] and stack.name == "stack"


def test_start_on_boot_alone_only_enables_or_disables(env):
    *_, node, _, calls, deployed = env
    _save(env, node, autostart=False)
    assert calls == [("control", "web", "disable")]
    calls.clear()
    deployed["yes"] = False                    # never deployed: nothing to enable
    _save(env, node, autostart=True)
    assert calls == [] and node.autostart is True


def test_the_edit_form_offers_every_setting():
    start = APP_JSX.index("{siteAppEdit?.id === app.id && <div className=\"user-edit-panel\">")
    form = APP_JSX[start:APP_JSX.index("</div>}\n          </div>)}", start)]
    for needle in ("siteAppEdit.name", "siteAppEdit.start_kind", "siteAppEdit.start_arg", "siteAppEdit.node_major",
                   "siteAppEdit.image", "siteAppEdit.container_port", "siteAppEdit.autostart", "siteAppEdit.cpu_limit",
                   "siteAppEdit.env", "siteAppEdit.port", "siteAppEdit.memory_limit_mb"):
        assert needle in form, needle
    assert "disabled={!!loading || app.kind === 'compose'}" in form
