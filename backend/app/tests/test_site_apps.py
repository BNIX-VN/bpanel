import pytest

from app.models.entities import SiteApp, User, UserPackage, Website
from app.services import site_apps


class _FakeScalars:
    def __init__(self, values):
        self._values = values

    def __iter__(self):
        return iter(self._values)


class _FakeSession:
    """Just enough Session for the port allocator and quota checks."""

    def __init__(self, ports=(), app_count=0):
        self._ports = list(ports)
        self._app_count = app_count

    def scalars(self, _query):
        return _FakeScalars(self._ports)

    def query(self, *_args):
        return self

    def join(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def count(self):
        return self._app_count


def _package(**kwargs):
    return UserPackage(name="Test", **kwargs)


def _user(package=None):
    user = User(id=1, username="tester", email="t@example.test", role="end_user")
    user.package = package
    return user


# --- names, kinds, ports ----------------------------------------------------

@pytest.mark.parametrize("name", ["app", "n8n", "my-app", "a1_b2", "x"])
def test_valid_app_names(name):
    assert site_apps.validate_name(name) == name


@pytest.mark.parametrize("name", ["", "-app", "app-", "App Name", "app/../x", "a" * 40, "ứng-dụng"])
def test_invalid_app_names(name):
    with pytest.raises(ValueError):
        site_apps.validate_name(name)


def test_port_must_sit_inside_the_managed_range():
    assert site_apps.validate_port(21000) == 21000
    assert site_apps.validate_port("21999") == 21999
    for bad in (80, 20999, 22000, 65536, "abc", None):
        with pytest.raises(ValueError):
            site_apps.validate_port(bad)


def test_allocate_port_skips_reserved_and_listening_ports(monkeypatch):
    monkeypatch.setattr(site_apps, "listening_ports", lambda: {21001})
    db = _FakeSession(ports=[21000])

    assert site_apps.allocate_port(db) == 21002


def test_allocate_port_honours_a_free_preference(monkeypatch):
    monkeypatch.setattr(site_apps, "listening_ports", lambda: set())

    assert site_apps.allocate_port(_FakeSession(), preferred=21500) == 21500


def test_allocate_port_rejects_a_taken_preference(monkeypatch):
    monkeypatch.setattr(site_apps, "listening_ports", lambda: {21500})

    with pytest.raises(ValueError, match="already in use"):
        site_apps.allocate_port(_FakeSession(), preferred=21500)


def test_allocate_port_reports_an_exhausted_range(monkeypatch):
    monkeypatch.setattr(site_apps, "listening_ports", lambda: set())
    db = _FakeSession(ports=list(range(site_apps.PORT_RANGE_START, site_apps.PORT_RANGE_END + 1)))

    with pytest.raises(ValueError, match="No free application port"):
        site_apps.allocate_port(db)


def test_listening_ports_parses_ss_output(monkeypatch):
    sample = (
        "LISTEN 0      511          0.0.0.0:80         0.0.0.0:*\n"
        "LISTEN 0      4096      127.0.0.1:21000      0.0.0.0:*\n"
        "LISTEN 0      4096         [::1]:21001          [::]:*\n"
        "garbage line\n"
    )
    monkeypatch.setattr(
        site_apps.shell,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": sample, "stderr": ""})(),
    )

    assert site_apps.listening_ports() == {80, 21000, 21001}


def test_listening_ports_is_empty_when_ss_is_missing(monkeypatch):
    monkeypatch.setattr(
        site_apps.shell,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 127, "stdout": "", "stderr": "not found"})(),
    )

    assert site_apps.listening_ports() == set()


# --- start command ----------------------------------------------------------

def test_start_command_accepts_the_supported_launchers():
    assert site_apps.validate_start("npm", "start", "app") == ("npm", "start")
    assert site_apps.validate_start("npx", "n8n", "app") == ("npx", "n8n")
    assert site_apps.validate_start("yarn", "start", "app") == ("yarn", "start")
    assert site_apps.validate_start("node", "server.js", "app") == ("node", "server.js")


@pytest.mark.parametrize(
    "start_kind,start_arg",
    [
        ("bash", "start"),
        ("npm", ""),
        ("npm", "start; rm -rf /"),
        ("npm", "start && curl evil"),
        ("npm", "$(whoami)"),
        ("npm", "start`id`"),
        ("node", "server.php"),
        ("node", "../../../etc/passwd.js"),
    ],
)
def test_start_command_rejects_anything_shell_shaped(start_kind, start_arg):
    with pytest.raises(ValueError):
        site_apps.validate_start(start_kind, start_arg, "app")


def test_node_entry_file_must_stay_inside_the_app_directory():
    assert site_apps.validate_start("node", "src/index.mjs", "app")[1] == "src/index.mjs"
    with pytest.raises(ValueError, match="inside the app directory"):
        site_apps.validate_start("node", "../outside.js", "app")


# --- app root, memory, node version ----------------------------------------

def test_app_root_defaults_and_rejects_escapes():
    assert site_apps.validate_app_root("") == "app"
    assert site_apps.validate_app_root("/app/") == "app"
    assert site_apps.validate_app_root("apps/n8n") == "apps/n8n"
    for bad in ("../secrets", "app/../..", "app/$(id)"):
        with pytest.raises(ValueError):
            site_apps.validate_app_root(bad)


def test_memory_limit_respects_the_package_ceiling():
    assert site_apps.validate_memory_mb(None) == site_apps.DEFAULT_MEMORY_MB
    assert site_apps.validate_memory_mb(1024, ceiling=2048) == 1024
    with pytest.raises(ValueError, match="at most 512 MB"):
        site_apps.validate_memory_mb(1024, ceiling=512)
    for bad in (0, 32, 99999, "lots"):
        with pytest.raises(ValueError):
            site_apps.validate_memory_mb(bad)


def test_node_major_validation():
    assert site_apps.validate_node_major("22") == "22"
    assert site_apps.validate_node_major(None) is None
    for bad in ("22.1", "v22", "9", "latest"):
        with pytest.raises(ValueError):
            site_apps.validate_node_major(bad)


# --- quota ------------------------------------------------------------------

def test_apps_are_off_without_a_package():
    with pytest.raises(ValueError, match="not enabled"):
        site_apps.ensure_app_quota(_FakeSession(), _user(), is_admin=False)


def test_apps_are_off_when_the_package_limit_is_zero():
    user = _user(_package(node_apps_limit=0))

    with pytest.raises(ValueError, match="not enabled"):
        site_apps.ensure_app_quota(_FakeSession(), user, is_admin=False)


def test_quota_blocks_once_the_limit_is_reached():
    user = _user(_package(node_apps_limit=2))

    site_apps.ensure_app_quota(_FakeSession(app_count=1), user, is_admin=False)
    with pytest.raises(ValueError, match="at most 2"):
        site_apps.ensure_app_quota(_FakeSession(app_count=2), user, is_admin=False)


def test_admins_are_not_held_to_a_package_quota():
    site_apps.ensure_app_quota(_FakeSession(app_count=99), _user(), is_admin=True)


# --- website helpers --------------------------------------------------------

def test_app_port_for_website_reads_the_first_app():
    website = Website(domain="example.test", owner_id=1, root_path="/home/u/example.test")
    assert site_apps.app_port_for_website(website) is None

    website.apps = [SiteApp(name="app", kind="proxy", port=21007, app_root="app")]
    assert site_apps.app_port_for_website(website) == 21007
