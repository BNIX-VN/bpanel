"""Redis per account addon (operator, 2026-10-27, DirectAdmin-style).

Each hosting account may turn on a Redis of its own, running as its own Linux
user behind a unix socket in its home; the administrator sets how much memory
it may hold per package (and per account without one): 64 MB unless changed,
0 = not allowed. These hold the helper to the config it renders and the
input it accepts, the API to who may turn it on, and the instances to the
database when a package, a limit or a suspension moves.
"""
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.models.entities import User, UserPackage
from app.services import addons, redis_accounts

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
UPDATE = (PROJECT_ROOT / "installer" / "update.sh").read_text(encoding="utf-8")


def _function(name):
    start = HELPER.index(f"\n{name}() {{") + 1
    return HELPER[start:HELPER.index("\n}\n", start) + 3]


def _case(label):
    body = HELPER[HELPER.index(f"\n  {label})\n"):]
    return body[:body.index(";;")]


# --- the registry -----------------------------------------------------------------

def test_it_is_an_addon_and_off_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path)
    monkeypatch.setattr(addons, "ADDONS_FILE", tmp_path / "addons.json")
    entry = addons.CATALOGUE[addons.REDIS_ACCOUNTS]
    assert addons.REDIS_ACCOUNTS == "redis-accounts"
    assert entry["name"] == "Redis per account"
    assert not addons.is_installed(addons.REDIS_ACCOUNTS)
    assert not redis_accounts.installed()
    notes = " ".join(entry["notes"])
    assert "/home/<user>/.redis/redis.sock" in notes
    assert "nothing is saved to disk" in notes and "0 MB" in notes
    assert "127.0.0.1:6379" in notes, "the server's own Redis is said to be left alone"


# --- the helper ----------------------------------------------------------------------

@pytest.mark.parametrize("verb", [
    "redis-install", "redis-uninstall", "redis-status", "redis-unit-refresh", "redis-disable", "redis-enable",
    "redis-user-apply", "redis-user-remove", "redis-user-status", "redis-user-flush",
])
def test_the_helper_has_the_verb(verb):
    assert f"\n  {verb})\n" in HELPER


def test_the_account_verbs_validate_the_account_and_the_memory():
    assert 'require_redis_user "$user"' in _function("redis_user_apply")
    assert 'require_redis_mb "$mb"' in _function("redis_user_apply")
    assert '"$slice" =~ $REDIS_SLICE_RE' in _function("redis_user_apply")
    # A hosting account's own user: the terminal's check (uid range, the SFTP
    # group, never a sudoer, a real home), and its group named after it.
    assert 'require_terminal_user "$1"' in _function("require_redis_user")
    for name in ("redis_user_status", "redis_user_flush"):
        assert 'require_redis_user "$user"' in _function(name)
    # Removal runs while an account is being deleted: the name is checked, and
    # nothing but paths named after it is touched.
    assert 'require_linux_user "$user"' in _function("redis_user_teardown")
    assert '[[ $# -eq 2 || $# -eq 3 ]]' in _case("redis-user-apply")
    for label in ("redis-user-remove", "redis-user-status", "redis-user-flush"):
        assert '[[ $# -eq 1 ]]' in _case(label)


def test_the_servers_own_redis_is_never_touched():
    """A box may already run redis-server.service on 127.0.0.1:6379, and the
    panel's rate limiter uses it."""
    install = _function("redis_install")
    assert 'if [[ ! -x "$REDIS_SERVER_BIN" ]]; then' in install
    assert "apt-get install -y redis-server" in install
    section = HELPER[HELPER.index("# --- Redis per account"):HELPER.index('\ncmd="${1:-}"')]
    # The code, not the comments that say what it leaves alone.
    section = "\n".join(line for line in section.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("redis-server.service", "systemctl stop redis-server", "systemctl disable redis-server",
                      "apt-get purge", "apt-get remove", "/etc/redis/redis.conf"):
        assert forbidden not in section, forbidden


def test_the_template_unit_runs_as_the_account_in_a_sandbox():
    unit = _function("redis_write_unit")
    for line in ("Type=notify", "User=%i", "Group=%i", "ExecStart=/usr/bin/redis-server /etc/bpanel-redis/%i.conf",
                 "Restart=on-failure", "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict",
                 "ProtectHome=read-only", "ReadWritePaths=/home/%i/.redis", "LimitNOFILE=1024"):
        assert f"\n{line}\n" in unit, line
    assert 'REDIS_UNIT="/etc/systemd/system/bpanel-redis@.service"' in HELPER


def test_apply_restarts_only_when_something_changed():
    apply = _function("redis_user_apply")
    # 0700: only the account (its PHP) reaches the socket.
    assert 'install -d -o "$user" -g "$user" -m 0700 "$dir"' in apply
    assert 'if [[ "$conf_state" == "changed" || "$dropin_state" == "changed" ]]; then' in apply
    assert 'systemctl restart "$unit"' in apply
    assert 'systemctl enable --now --quiet "$unit"' in apply
    assert 'cmp -s "$tmp" "$target"' in _function("redis_put_file")


def test_removal_and_uninstall_take_everything_but_the_package():
    teardown = _function("redis_user_teardown")
    assert 'systemctl disable --now "$unit"' in teardown
    assert 'rm -f "$REDIS_CONF_DIR/$user.conf"' in teardown
    assert 'rm -rf "$dropin"' in teardown
    assert 'rm -rf --one-file-system "$HOME_ROOT/$user/.redis"' in teardown
    uninstall = _function("redis_uninstall")
    assert "redis_user_teardown" in uninstall and 'rm -f "$REDIS_UNIT"' in uninstall
    # Stopped, the configurations kept; started again from them.
    assert "systemctl stop 'bpanel-redis@*.service'" in _function("redis_disable")
    assert '[[ -f "$REDIS_CONF_DIR/$user.conf" ]] || continue' in _function("redis_enable")


def test_deleting_an_account_removes_its_redis_whichever_path_deletes_it():
    """users.delete_user, provisioning's terminate and the DirectAdmin import
    all end in the helper's panel-user-delete."""
    body = _function("delete_panel_user_runtime")
    assert body.index('redis_user_teardown "$user"') < body.index('pkill -u "$user"')


def test_status_and_flush_talk_to_the_socket_as_the_account():
    status = _function("redis_user_status")
    assert 'runuser -u "$user" -- redis-cli -s "$HOME_ROOT/$user/.redis/redis.sock" INFO memory' in status
    assert "used_memory" in status
    flush = _function("redis_user_flush")
    assert 'runuser -u "$user" -- redis-cli -s "$HOME_ROOT/$user/.redis/redis.sock" FLUSHALL' in flush


def test_no_redis_function_ends_on_a_test_that_can_fail():
    """Under set -e a function whose last command is a false [[ ]] && cmd
    returns 1 and takes the helper down with it."""
    section = HELPER[HELPER.index("# --- Redis per account"):HELPER.index('\ncmd="${1:-}"')]
    for match in re.finditer(r"\n([a-z_]+)\(\) \{\n(.*?)\n\}\n", section, flags=re.S):
        last = match.group(2).strip().splitlines()[-1].strip()
        assert not re.match(r"^\[\[.*\]\] && ", last), f"{match.group(1)} ends on {last!r}"


def test_the_updater_refreshes_the_unit_where_the_addon_is_installed():
    block = UPDATE[UPDATE.index("# --- Redis per account: the template unit"):]
    block = block[:block.index("\nfi\n")]
    assert "if [[ -f /etc/systemd/system/bpanel-redis@.service ]]" in block
    assert "bpanel-helper redis-unit-refresh" in block


needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _bash(*functions, call):
    script = "\n".join([
        "set -euo pipefail",
        "HOME_ROOT=/home",
        'deny() { echo "bpanel-helper: $*" >&2; exit 1; }',
        *(_function(name) for name in functions),
        call,
    ])
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


@needs_bash
def test_the_config_is_a_cache_on_a_socket():
    out = _bash("redis_user_config", call="redis_user_config alice 64")
    assert out.returncode == 0, out.stderr
    lines = [line for line in out.stdout.splitlines() if line and not line.startswith("#")]
    assert lines == [
        "port 0",
        "unixsocket /home/alice/.redis/redis.sock",
        "unixsocketperm 700",
        "dir /home/alice/.redis",
        "maxmemory 64mb",
        "maxmemory-policy allkeys-lru",
        'save ""',
        "appendonly no",
        "supervised systemd",
        "daemonize no",
        'logfile ""',
        "databases 16",
        "protected-mode yes",
    ]


@needs_bash
@pytest.mark.parametrize("mb, ok", [
    ("1", True), ("64", True), ("4096", True),
    ("0", False), ("4097", False), ("-1", False), ("064", False), ("64mb", False), ("", False), ("1 2", False),
])
def test_the_memory_must_be_1_to_4096_mb(mb, ok):
    out = _bash("require_redis_mb", call=f"require_redis_mb '{mb}' && echo accepted")
    assert (out.returncode == 0 and "accepted" in out.stdout) is ok, out.stderr


@needs_bash
def test_the_systemd_ceiling_sits_above_maxmemory_and_names_the_slice():
    out = _bash("redis_memory_max_mb", "redis_user_dropin", call="redis_user_dropin 64 hosting-r3-a12.slice")
    assert out.returncode == 0, out.stderr
    assert "[Service]\nMemoryMax=96M\nSlice=hosting-r3-a12.slice\n" in out.stdout
    out = _bash("redis_memory_max_mb", "redis_user_dropin", call="redis_user_dropin 1024 ''")
    assert "MemoryMax=1296M\n" in out.stdout and "Slice=" not in out.stdout


@needs_bash
@pytest.mark.parametrize("slice_name, ok", [
    ("hosting-a12.slice", True), ("hosting-r3-a12.slice", True),
    ("system.slice", False), ("hosting-r3.slice", False), ("hosting-a12.slice;x", False),
])
def test_the_slice_is_an_accounts(slice_name, ok):
    script = HELPER[HELPER.index("REDIS_SLICE_RE="):].split("\n", 1)[0]
    out = _bash(call=f"{script}\nif [[ '{slice_name}' =~ $REDIS_SLICE_RE ]]; then echo yes; fi")
    assert ("yes" in out.stdout) is ok


# --- the effective limit -------------------------------------------------------------

def test_the_package_wins_and_a_custom_account_has_its_own():
    package = SimpleNamespace(redis_memory_mb=256)
    assert redis_accounts.limit_mb(SimpleNamespace(package=package, redis_memory_mb=64)) == 256
    assert redis_accounts.limit_mb(SimpleNamespace(package=SimpleNamespace(redis_memory_mb=0), redis_memory_mb=64)) == 0
    assert redis_accounts.limit_mb(SimpleNamespace(package=None, redis_memory_mb=128)) == 128
    assert redis_accounts.limit_mb(SimpleNamespace(package=None, redis_memory_mb=99999)) == redis_accounts.MAX_MB
    assert redis_accounts.limit_mb(None) == 0


def test_the_defaults_are_64_mb_and_off():
    assert User.__table__.c.redis_memory_mb.default.arg == 64
    assert User.__table__.c.redis_enabled.default.arg is False
    assert UserPackage.__table__.c.redis_memory_mb.default.arg == 64


def test_the_status_line_is_parsed():
    assert redis_accounts.parse_status("state=active used_memory=1048576 configured=yes\n") == {
        "running": True, "used_bytes": 1048576, "configured": True}
    assert redis_accounts.parse_status("state=inactive used_memory=junk configured=no") == {
        "running": False, "used_bytes": 0, "configured": False}


# --- the API and the reconciling -----------------------------------------------------

@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    people = {}
    for name, role in (("root_admin", "admin"), ("alice", "end_user"), ("bob", "end_user")):
        people[name] = User(username=name, email=f"{name}@example.test", role=role, is_active=True,
                            hashed_password=hash_password("PasswordLongEnough1"))
        db.add(people[name])
    db.commit()

    calls = []
    answers = {}

    def fake_privileged(command, helper_args=None, check=True, input=None, sensitive=False, fallback=None, timeout=None):
        calls.append((command, list(helper_args or [])))
        code, out = answers.get(command, (0, "state=active used_memory=2048 configured=yes\n"))
        return SimpleNamespace(returncode=code, stdout=out, stderr="" if code == 0 else out)

    addon = {"on": True}
    instances = set()
    scheduled = []
    monkeypatch.setattr(redis_accounts.shell, "privileged", fake_privileged)
    monkeypatch.setattr(redis_accounts, "installed", lambda: addon["on"])
    monkeypatch.setattr(redis_accounts, "_has_instance", lambda name: name in instances)
    monkeypatch.setattr(redis_accounts, "reconcile_in_background", lambda ids: scheduled.append(sorted(ids)))

    from app.main import app

    def get_test_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    state = {"name": "alice"}

    # The signed-in account from the request's own session, as the real
    # dependency gives it.
    def current_user(session=Depends(get_db)):
        return session.query(User).filter(User.username == state["name"]).one()

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = current_user
    client = TestClient(app)

    def as_user(name):
        state["name"] = name
        return client

    def user(name):
        db.expire_all()
        return db.query(User).filter(User.username == name).one()

    try:
        yield SimpleNamespace(db=db, client=client, calls=calls, answers=answers, addon=addon,
                              instances=instances, scheduled=scheduled, as_user=as_user, user=user)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        db.close()


def test_the_page_says_whether_it_is_allowed(env):
    body = env.as_user("alice").get("/api/redis").json()
    assert body["installed"] is True and body["allowed"] is True
    assert body["limit_mb"] == 64 and body["enabled"] is False and body["running"] is False
    assert body["socket"] == "/home/alice/.redis/redis.sock"
    assert env.calls == [], "nothing to ask the helper while it is off"
    admin = env.as_user("root_admin").get("/api/redis").json()
    assert admin["allowed"] is False and admin["problem"] == "admin" and admin["socket"] is None


def test_turning_it_on_starts_the_accounts_redis_in_its_slice(env):
    alice = env.user("alice")
    response = env.as_user("alice").post("/api/redis/enable")
    assert response.status_code == 200, response.text
    assert ("redis-user-apply", ["alice", "64", f"hosting-a{alice.id}.slice"]) in env.calls
    assert env.user("alice").redis_enabled is True
    body = response.json()
    assert body["enabled"] is True and body["running"] is True and body["used_bytes"] == 2048


def test_it_is_refused_without_the_addon(env):
    env.addon["on"] = False
    assert env.as_user("alice").post("/api/redis/enable").status_code == 409
    assert env.as_user("alice").post("/api/redis/flush").status_code == 409
    assert env.as_user("alice").get("/api/redis").json()["installed"] is False
    assert env.calls == []


def test_it_is_refused_when_the_package_allows_none(env):
    package = UserPackage(name="NoRedis", redis_memory_mb=0)
    env.db.add(package)
    env.db.commit()
    alice = env.user("alice")
    alice.package_id = package.id
    env.db.commit()
    response = env.as_user("alice").post("/api/redis/enable")
    assert response.status_code == 403
    assert response.json()["detail"] == "Redis is not part of this account's package."
    assert env.as_user("alice").get("/api/redis").json()["allowed"] is False
    assert env.user("alice").redis_enabled is False and env.calls == []


def test_it_is_refused_to_a_suspended_account_and_an_administrator(env):
    alice = env.user("alice")
    alice.is_active = False
    env.db.commit()
    assert env.as_user("alice").post("/api/redis/enable").status_code == 403
    assert env.as_user("root_admin").post("/api/redis/enable").status_code == 403
    assert env.calls == []


def test_a_redis_that_does_not_start_is_not_left_on(env):
    env.answers["redis-user-apply"] = (1, "bpanel-helper: the Redis of alice did not start -- check: journalctl")
    response = env.as_user("alice").post("/api/redis/enable")
    assert response.status_code == 400
    assert "did not start" in response.json()["detail"]
    assert env.user("alice").redis_enabled is False


def test_off_and_empty(env):
    alice = env.user("alice")
    alice.redis_enabled = True
    env.db.commit()
    assert env.as_user("alice").post("/api/redis/flush").status_code == 200
    assert ("redis-user-flush", ["alice"]) in env.calls
    assert env.as_user("alice").post("/api/redis/disable").status_code == 200
    assert ("redis-user-remove", ["alice"]) in env.calls
    assert env.user("alice").redis_enabled is False
    assert env.as_user("alice").post("/api/redis/flush").status_code == 400, "nothing to empty while it is off"


def test_the_accounts_list_is_the_administrators(env):
    assert env.as_user("alice").get("/api/redis/accounts").status_code == 403
    items = env.as_user("root_admin").get("/api/redis/accounts").json()["items"]
    assert [item["username"] for item in items] == ["alice", "bob"]
    assert items[0]["limit_mb"] == 64 and items[0]["enabled"] is False


def test_editing_the_package_reapplies_its_accounts_redis(env):
    package = UserPackage(name="Basic", redis_memory_mb=64)
    env.db.add(package)
    env.db.commit()
    for name, on in (("alice", True), ("bob", False)):
        account = env.user(name)
        account.package_id = package.id
        account.redis_enabled = on
        env.db.commit()
    alice_id = env.user("alice").id

    response = env.as_user("root_admin").patch(f"/api/packages/{package.id}", json={"redis_memory_mb": 256})
    assert response.status_code == 200, response.text
    assert response.json()["redis_memory_mb"] == 256
    assert env.scheduled == [[alice_id]], "only the accounts that have it on, once"
    # What the background run does for each of them.
    assert redis_accounts.reconcile(env.db, env.user("alice")) == "applied"
    assert env.calls[-1] == ("redis-user-apply", ["alice", "256", f"hosting-a{alice_id}.slice"])

    env.scheduled.clear()
    env.as_user("root_admin").patch(f"/api/packages/{package.id}", json={"website_limit": 9})
    assert env.scheduled == [], "a change that is not the Redis size restarts nothing"


def test_a_package_that_drops_to_zero_turns_it_off(env):
    package = UserPackage(name="Basic", redis_memory_mb=0)
    env.db.add(package)
    env.db.commit()
    alice = env.user("alice")
    alice.package_id = package.id
    alice.redis_enabled = True
    env.db.commit()
    env.instances.add("alice")
    assert redis_accounts.reconcile(env.db, env.user("alice")) == "removed"
    assert env.calls == [("redis-user-remove", ["alice"])]
    assert env.user("alice").redis_enabled is False


def test_switching_package_or_custom_limit_reapplies(env):
    alice = env.user("alice")
    alice.redis_enabled = True
    env.db.commit()
    response = env.as_user("root_admin").patch(f"/api/users/{alice.id}", json={"redis_memory_mb": 512})
    assert response.status_code == 200, response.text
    assert response.json()["redis_memory_mb"] == 512
    assert env.calls[-1] == ("redis-user-apply", ["alice", "512", f"hosting-a{alice.id}.slice"])


def test_suspending_stops_it_and_keeps_the_switch(env):
    alice = env.user("alice")
    alice.redis_enabled = True
    env.db.commit()
    env.instances.add("alice")
    assert env.as_user("root_admin").post(f"/api/users/{alice.id}/suspend").status_code == 200
    assert ("redis-user-remove", ["alice"]) in env.calls
    assert env.user("alice").redis_enabled is True, "it comes back with the account"
    env.calls.clear()
    env.instances.discard("alice")
    assert env.as_user("root_admin").post(f"/api/users/{alice.id}/unsuspend").status_code == 200
    assert env.calls == [("redis-user-apply", ["alice", "64", f"hosting-a{alice.id}.slice"])]


def test_an_account_without_it_costs_no_helper_call(env):
    assert redis_accounts.reconcile(env.db, env.user("bob")) == "none"
    assert env.calls == []


def test_a_reseller_cannot_hand_out_more_than_its_own(env):
    from app.services import reseller

    own = SimpleNamespace(role="reseller", terminal_enabled=False, package=None, redis_memory_mb=64)
    reseller.check_package_grants(own, SimpleNamespace(terminal_enabled=False, redis_memory_mb=64))
    with pytest.raises(ValueError, match="64 MB"):
        reseller.check_package_grants(own, SimpleNamespace(terminal_enabled=False, redis_memory_mb=128))
    env.addon["on"] = False
    reseller.check_package_grants(own, SimpleNamespace(terminal_enabled=False, redis_memory_mb=128))


def test_removing_the_addon_turns_every_switch_off(env):
    alice = env.user("alice")
    alice.redis_enabled = True
    env.db.commit()
    assert redis_accounts.uninstall(env.db) == 1
    assert env.calls == [("redis-uninstall", [])]
    assert env.user("alice").redis_enabled is False
