"""Every site's PHP disables the dangerous functions until its owner takes one
off (operator, 2026-11-08): exec, system, passthru, shell_exec, proc_open...

The helper writes them into the site's PHP-FPM pool as
php_admin_value[disable_functions] - the default list unless the site has its
own - so every site, existing ones included, gets it at the next pool rewrite.
"""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import websites as api
from app.core.database import Base
from app.models.entities import User, Website
from app.services import php_functions, site_users

ROOT = Path(__file__).resolve().parents[3]
HELPER = (ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = HELPER.index(f"\n{name}() {{\n") + 1
    return HELPER[start:HELPER.index("\n}\n", start)]


def test_one_default_list_in_the_helper_the_service_and_the_page():
    helper = re.search(r'^PHP_DEFAULT_DISABLE_FUNCTIONS="([^"]+)"$', HELPER, re.M).group(1).split(",")
    page = re.findall(r"'([a-z_]+)'", APP[APP.index("const PHP_DEFAULT_DISABLED = ["):APP.index("];", APP.index("const PHP_DEFAULT_DISABLED = ["))])
    assert helper == list(php_functions.DEFAULT_DISABLED) == page
    assert {"exec", "system", "passthru", "shell_exec", "proc_open", "posix_uname"} <= set(helper)


def test_the_pool_carries_the_list_as_an_admin_value():
    pool = _function("ensure_php_pool")
    assert 'disable_list="$(site_php_disable_list "$user" "$target")"' in pool
    assert '[[ -n "$disable_list" ]] && disable_line="php_admin_value[disable_functions] = ${disable_list}"' in pool
    assert "${basedir_line}\n${disable_line}\n" in pool
    listing = _function("site_php_disable_list")
    assert 'printf \'%s\' "$PHP_DEFAULT_DISABLE_FUNCTIONS"' in listing, "no marker: the default list"
    assert listing.count("PHP_DEFAULT_DISABLE_FUNCTIONS") == 2, "a marker that is not a list falls back to the default"


def test_the_list_follows_the_site_and_goes_with_it():
    assert 'rm -f "$(site_php_disable_marker "$user" "$target")"' in _function("delete_site_php_pools")
    assert 'rm -f "${PHP_DISABLE_ROOT}/${user}-"* 2>/dev/null || true' in HELPER
    move = HELPER[HELPER.index("  site-runtime-move)\n"):]
    move = move[:move.index("\n    ;;\n")]
    assert move.index('disable_marker="$(site_php_disable_marker "$old_user" "$old_target")"') < move.index("delete_site_php_pools")
    assert 'set_site_php_disable "$user" "$new_target" "$disable_state"' in move
    verb = HELPER[HELPER.index("  site-php-disable)\n"):]
    verb = verb[:verb.index("\n    ;;\n")]
    assert 'set_site_php_disable "$user" "$target" "$value"' in verb and 'ensure_php_pool "$user" "$target" "$php_version"' in verb


def test_the_helper_takes_only_a_list_of_names():
    check = _function("require_php_function_list")
    assert '^[a-z_][a-z0-9_]*(,[a-z_][a-z0-9_]*)*$' in check
    assert '"default" || "$value" == "none"' in check


@pytest.mark.parametrize("text, expected", [
    (None, None),
    ("", ""),
    ("exec, system\nEXEC,popen", "exec,system,popen"),
])
def test_normalize(text, expected):
    assert php_functions.normalize(text) == expected


@pytest.mark.parametrize("text", ["exec;rm -rf /", "a,b c$", "1abc"])
def test_normalize_refuses_what_is_not_a_function_name(text):
    with pytest.raises(ValueError):
        php_functions.normalize(text)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    people = {}
    for name in ("alice", "bob"):
        people[name] = User(username=name, email=f"{name}@example.test", role="end_user", is_active=True,
                            hashed_password="x", token_version=0)
        db.add(people[name])
    db.commit()
    site = Website(domain="shop.test", owner_id=people["alice"].id, root_path="/home/alice/shop.test",
                   linux_user="alice", app_type="wordpress", php_version="8.3")
    db.add(site)
    db.commit()
    calls = []
    monkeypatch.setattr(site_users, "set_php_disable", lambda root, version, user, value: calls.append((root, version, user, value)))
    monkeypatch.setattr(api, "log_action", lambda *a, **k: None)
    yield db, people, site, calls
    db.close()


def _put(env, who, functions):
    db, people, site, _ = env
    return api.set_website_disable_functions(site.id, api.WebsiteDisableFunctions(functions=functions),
                                             request=SimpleNamespace(client=None, headers={}), db=db, current_user=people[who])


def test_the_owner_takes_a_function_off_and_goes_back_to_the_default(env):
    _, _, site, calls = env
    assert php_functions.effective(site) == list(php_functions.DEFAULT_DISABLED)
    out = _put(env, "alice", "system,passthru")
    assert out.disable_functions == "system,passthru" and calls[-1][3] == "system,passthru"
    assert _put(env, "alice", "").disable_functions == "" and calls[-1][3] == "none"
    assert _put(env, "alice", None).disable_functions is None and calls[-1][3] == "default"


def test_another_customer_cannot(env):
    _, _, _, calls = env
    with pytest.raises(HTTPException) as err:
        _put(env, "bob", "")
    assert err.value.status_code in (403, 404) and calls == []
