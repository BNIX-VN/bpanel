"""open_basedir per site and per package, and the wall that lets it be off.

open_basedir cost a third of every uncached WordPress page on .88
(2026-10-23), so it became opt-in, as in OPanel 1.36.0: off by default, on
for the sites of a package that has it, settable per site by the host. That is
only safe because /home/<user> stopped being traversable by other customers.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import User, UserPackage, Website
from app.services import php_isolation, site_users

ROOT = Path(__file__).resolve().parents[3]
HELPER = (ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
INSTALL = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
UPDATE = (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")


def _function(script: str, name: str) -> str:
    return script.split(f"\n{name}() {{\n", 1)[1].split("\n}\n", 1)[0]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(site_users, "set_php_basedir",
                        lambda root, php, user, on: seen.append((root, php, user, on)))
    return seen


def _account(db, package=None, name="alice"):
    user = User(username=name, email=f"{name}@example.test", hashed_password="x", role="user",
                package_id=package.id if package else None)
    db.add(user)
    db.commit()
    return user


def _site(db, owner, domain, app_type="wordpress", on=False):
    site = Website(domain=domain, owner_id=owner.id, root_path=f"/home/{owner.username}/{domain}",
                   linux_user=owner.username, php_version="8.3", app_type=app_type, status="active",
                   open_basedir=on)
    db.add(site)
    db.commit()
    return site


def test_a_site_is_off_unless_its_package_says_on(db):
    plain = UserPackage(name="Basic")
    fenced = UserPackage(name="Shared", open_basedir=True)
    db.add_all([plain, fenced])
    db.commit()
    assert php_isolation.default_for(db, _account(db, None, "nopkg")) is False
    assert php_isolation.default_for(db, _account(db, plain, "basic")) is False
    assert php_isolation.default_for(db, _account(db, fenced, "shared")) is True
    assert Website.__table__.c.open_basedir.server_default.arg.text == "0"


def test_turning_a_package_on_moves_every_site_of_its_accounts(db, calls):
    package = UserPackage(name="Shared")
    other = UserPackage(name="Other")
    db.add_all([package, other])
    db.commit()
    alice, bob, carol = _account(db, package, "alice"), _account(db, package, "bob"), _account(db, other, "carol")
    a1, a2, b1 = _site(db, alice, "a1.test"), _site(db, alice, "a2.test", app_type="static"), _site(db, bob, "b1.test")
    c1 = _site(db, carol, "c1.test")

    package.open_basedir = True
    db.commit()
    assert php_isolation.sync_package(db, package) == []

    assert {c[0] for c in calls} == {a1.root_path, a2.root_path, b1.root_path}
    # A static site has no pool: the marker is still kept, for a mode change later.
    assert (a2.root_path, None, "alice", True) in calls
    for site in (a1, a2, b1):
        db.refresh(site)
        assert site.open_basedir is True
    db.refresh(c1)
    assert c1.open_basedir is False


def test_a_site_already_at_the_value_is_not_rewritten(db, calls):
    package = UserPackage(name="Shared", open_basedir=True)
    db.add(package)
    db.commit()
    alice = _account(db, package)
    _site(db, alice, "on.test", on=True)
    off = _site(db, alice, "off.test")
    php_isolation.sync_user(db, alice)
    assert [c[0] for c in calls] == [off.root_path]


def test_an_account_without_a_package_keeps_what_its_sites_have(db, calls):
    alice = _account(db)
    site = _site(db, alice, "a.test", on=True)
    assert php_isolation.sync_user(db, alice) == []
    assert calls == []
    db.refresh(site)
    assert site.open_basedir is True


def test_a_pool_that_cannot_be_rewritten_keeps_its_old_value(db, monkeypatch):
    def fail(*_args):
        raise RuntimeError("helper said no")

    monkeypatch.setattr(site_users, "set_php_basedir", fail)
    alice = _account(db)
    site = _site(db, alice, "a.test")
    assert php_isolation.apply(db, [site], True) == ["a.test"]
    db.refresh(site)
    assert site.open_basedir is False


def test_the_helper_writes_open_basedir_only_for_a_marked_site():
    pool = _function(HELPER, "ensure_php_pool")
    assert 'if [[ -f "${PHP_BASEDIR_ROOT}/${user}-${site_hash}" ]]; then' in pool
    assert "\n${basedir_line}\n" in pool
    on = pool.split('basedir_line="php_admin_value[open_basedir] = ', 1)[1].split('"', 1)[0]
    assert on == "${target}:${sess_dir}:${upload_dir}:${tmp_dir}:/usr/share/php"
    # Off is a comment, so the pool file says why there is no line.
    assert 'local basedir_line=";php_admin_value[open_basedir] is off' in pool
    assert 'PHP_BASEDIR_ROOT="/etc/bpanel/php-basedir"' in HELPER


def test_the_marker_lives_and_dies_with_the_site():
    verb = HELPER.split("  site-php-basedir)\n", 1)[1].split("\n    ;;\n", 1)[0]
    assert 'target=$(require_managed_path "$path" "$user")' in verb
    assert '[[ "$state" == "on" || "$state" == "off" ]] || deny' in verb
    assert verb.index("set_site_php_basedir") < verb.index("ensure_php_pool")
    assert 'rm -f "$(site_php_basedir_marker "$user" "$target")"' in _function(HELPER, "delete_site_php_pools")
    assert 'rm -f "${PHP_BASEDIR_ROOT}/${user}-"*' in _function(HELPER, "delete_panel_user_runtime")
    move = HELPER.split("  site-runtime-move)\n", 1)[1].split("\n    ;;\n", 1)[0]
    assert move.index('site_php_basedir_marker "$old_user" "$old_target"') < move.index("delete_site_php_pools")
    assert 'set_site_php_basedir "$user" "$new_target" "$basedir_state"' in move
    # Root's directory: the panel account cannot plant or remove a marker
    # except through the verb.
    assert 'install -d -o root -g root -m 0755 "$PHP_BASEDIR_ROOT"' in _function(HELPER, "set_site_php_basedir")


def test_homes_are_closed_to_other_customers():
    """With open_basedir off, a customer's PHP could read any other customer's
    0644 site files through a 0751 home whose name /etc/passwd gives away.
    0750 closes that; the panel keeps exactly the traverse it had, through an
    ACL rather than "other"."""
    home = _function(HELPER, "ensure_panel_user_home")
    assert 'chmod 0750 "$home_dir"' in home
    assert home.index("clear_path_acl") < home.index('allow_panel_traverse "$home_dir"')
    assert "setfacl -m u:bpanel:x" in _function(HELPER, "allow_panel_traverse")
    users = _function(UPDATE, "harden_existing_panel_users")
    assert 'chmod 0750 "$home_dir"' in users and "0751" not in users
    assert users.index("setfacl -b -k") < users.index("setfacl -m u:bpanel:x")


@pytest.mark.parametrize("script", [INSTALL, UPDATE], ids=["install", "update"])
def test_nginx_and_the_network_are_tuned_on_install_and_update(script):
    calls = script.split("configure_proxy_upgrade_map\n")[-1]
    assert "configure_nginx_performance" in calls and "configure_network_tuning" in calls
    nginx = _function(script, "configure_nginx_performance")
    for directive in ("open_file_cache max=20000 inactive=60s;", "ssl_session_cache shared:BPANEL_SSL:20m;",
                      "keepalive_requests 1000;"):
        assert directive in nginx
    # nginx.conf has gzip_types already; a second one makes nginx -t fail.
    assert "gzip" not in nginx
    network = _function(script, "configure_network_tuning")
    assert 'echo "net.ipv4.tcp_congestion_control = bbr"' in network
    assert 'if [[ "$bbr" == "1" ]]; then' in network
    assert "sysctl -q -p" in network
