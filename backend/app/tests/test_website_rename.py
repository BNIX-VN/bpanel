"""The rename-domain endpoint (DirectAdmin-style change-a-domain), BPanel.

The file move + vhost rewrite + record flip is the atomic-ish core; once it is
done the site serves under the new name and the rest (certificate, DNS, mail,
WordPress, cron, SFTP/Git) is best effort. These tests pin the core order and
that every follow-up primitive is called with the old and new names.
"""
import app.services.mail as mailmod
import app.services.wp_manager as wpmanmod
from app.api import websites
from app.models.entities import GitRepository, SftpAccount, User, Website, WebsiteAlias


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, website, git_repos=None, sftp=None):
        self.website = website
        self.git_repos = git_repos or []
        self.sftp = sftp or []
        self.committed = 0

    def query(self, model):
        if model is Website:
            return _Query([self.website])
        if model is GitRepository:
            return _Query(self.git_repos)
        if model is SftpAccount:
            return _Query(self.sftp)
        return _Query([])

    def commit(self):
        self.committed += 1

    def refresh(self, item):
        pass


def _patch_services(monkeypatch, calls, *, conflict=False):
    monkeypatch.setattr(websites, "_block_if_source", lambda *a, **k: None)
    monkeypatch.setattr(websites, "_hostname_conflicts", lambda *a, **k: conflict)
    monkeypatch.setattr(websites, "_has_wordpress_install", lambda website: False)
    monkeypatch.setattr(websites, "_sync_http_flood_zones", lambda db: None)
    monkeypatch.setattr(websites, "log_action", lambda *a, **k: None)
    monkeypatch.setattr(websites.nginx, "vhost_exists", lambda domain: False)
    monkeypatch.setattr(websites.site_users, "site_root_for_panel_user",
                        lambda username, domain: f"/home/{username}/{domain}")
    monkeypatch.setattr(websites.site_users, "move_site_runtime",
                        lambda old, new, user, php: calls.setdefault("move", []).append((old, new, user, php)) or new)
    monkeypatch.setattr(websites.waf, "sync_website_rules",
                        lambda website: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(websites.waf, "remove_site_rules",
                        lambda domain: calls.setdefault("waf_remove", []).append(domain) or "")
    monkeypatch.setattr(websites, "_rewrite_website_vhost",
                        lambda website, **kw: calls.setdefault("vhost", []).append((website.domain, kw.get("root_path"))) or "/vhost.conf")
    monkeypatch.setattr(websites.nginx, "delete_wordpress_vhost",
                        lambda domain: calls.setdefault("delete_vhost", []).append(domain))
    monkeypatch.setattr(websites.ssl, "release_site_certificates",
                        lambda db, domain, exclude_website_id=None: calls.setdefault("ssl_release", []).append(domain) or "")
    monkeypatch.setattr(websites.ssl, "issue_ssl",
                        lambda domain, aliases: calls.setdefault("issue", []).append((domain, list(aliases))) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(websites.dns, "zone_for_new_domain",
                        lambda db, domain, owner_id: calls.setdefault("dns", []).append((domain, owner_id)))
    monkeypatch.setattr(websites.cron, "rewrite_website_domain",
                        lambda old, new, oldr, newr, user: calls.setdefault("cron", []).append((old, new, oldr, newr, user)))
    monkeypatch.setattr(websites.sftp_accounts, "repoint_account",
                        lambda owner, sub, newr: calls.setdefault("sftp", []).append((owner, sub, newr)))
    monkeypatch.setattr(websites.wordpress, "rename_site_url",
                        lambda *a, **k: calls.setdefault("wp", []).append((a, k)))
    monkeypatch.setattr(wpmanmod, "forget_website",
                        lambda db, website_id: calls.setdefault("wp_forget", []).append(website_id))
    monkeypatch.setattr(mailmod, "migrate_domain",
                        lambda db, old, new, owner_id=None: calls.setdefault("mail", []).append((old, new, owner_id)))


def _site(**overrides):
    website = Website(
        id=1,
        domain="old.test",
        owner_id=1,
        root_path="/home/alice/old.test",
        linux_user="alice",
        app_type="static",
        php_version="8.3",
        ssl_enabled=False,
        ssl_mode="none",
        status="active",
        http_flood_enabled=False,
    )
    website.aliases = []
    website.owner = User(id=1, username="alice", role="user")
    for key, value in overrides.items():
        setattr(website, key, value)
    return website


def test_rename_moves_files_rewrites_vhost_and_flips_record(monkeypatch):
    website = _site()
    db = _Db(website)
    calls = {}
    _patch_services(monkeypatch, calls)
    from app.schemas.schemas import WebsiteRename

    result = websites.rename_website(
        1, WebsiteRename(new_domain="New.Test"), request=None, db=db,
        current_user=User(id=9, role="admin"),
    )

    assert result["ok"] is True
    assert result["domain"] == "new.test"
    assert website.domain == "new.test"
    assert website.root_path == "/home/alice/new.test"
    assert calls["move"] == [("/home/alice/old.test", "/home/alice/new.test", "alice", None)]
    assert calls["vhost"][0] == ("new.test", "/home/alice/new.test")
    assert calls["delete_vhost"] == ["old.test"]
    assert calls["waf_remove"] == ["old.test"]
    assert calls["ssl_release"] == ["old.test"]
    assert calls["dns"] == [("new.test", 1)]
    assert calls["cron"] == [("old.test", "new.test", "/home/alice/old.test", "/home/alice/new.test", "alice")]
    assert calls["mail"] == [("old.test", "new.test", 1)]
    assert db.committed >= 1


def test_rename_rejects_same_domain(monkeypatch):
    website = _site()
    calls = {}
    _patch_services(monkeypatch, calls)
    from app.schemas.schemas import WebsiteRename
    try:
        websites.rename_website(1, WebsiteRename(new_domain="old.test"), request=None,
                                db=_Db(website), current_user=User(id=9, role="admin"))
    except websites.HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected an HTTPException for an unchanged domain")


def test_rename_rejects_taken_domain(monkeypatch):
    website = _site()
    calls = {}
    _patch_services(monkeypatch, calls, conflict=True)
    from app.schemas.schemas import WebsiteRename
    try:
        websites.rename_website(1, WebsiteRename(new_domain="taken.test"), request=None,
                                db=_Db(website), current_user=User(id=9, role="admin"))
    except websites.HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("expected an HTTPException for a taken domain")
    assert "move" not in calls


def test_rename_reissues_letsencrypt_for_the_new_name(monkeypatch):
    website = _site(ssl_enabled=True, ssl_mode="letsencrypt")
    db = _Db(website)
    calls = {}
    _patch_services(monkeypatch, calls)
    from app.schemas.schemas import WebsiteRename

    websites.rename_website(1, WebsiteRename(new_domain="new.test", reissue_ssl=True),
                            request=None, db=db, current_user=User(id=9, role="admin"))

    assert calls["ssl_release"] == ["old.test"]
    assert calls["issue"] == [("new.test", [])]
    assert website.ssl_enabled is True
    assert website.ssl_mode == "letsencrypt"


def test_rename_rewrites_git_repo_paths_under_the_old_root(monkeypatch):
    website = _site()
    repo_in = GitRepository(id=1, owner_id=1, name="app", path="/home/alice/old.test/app")
    repo_out = GitRepository(id=2, owner_id=1, name="other", path="/home/alice/scripts")
    db = _Db(website, git_repos=[repo_in, repo_out])
    calls = {}
    _patch_services(monkeypatch, calls)
    from app.schemas.schemas import WebsiteRename

    websites.rename_website(1, WebsiteRename(new_domain="new.test"), request=None, db=db,
                            current_user=User(id=9, role="admin"))

    assert repo_in.path == "/home/alice/new.test/app"
    assert repo_out.path == "/home/alice/scripts"


def test_rename_rolls_back_when_the_vhost_fails(monkeypatch):
    website = _site()
    db = _Db(website)
    calls = {}
    _patch_services(monkeypatch, calls)
    from app.schemas.schemas import WebsiteRename

    def boom(wbsite, **kw):
        if wbsite.domain == "new.test" and kw.get("root_path"):
            raise RuntimeError("config broke")
        return "/vhost.conf"
    monkeypatch.setattr(websites, "_rewrite_website_vhost", boom)

    try:
        websites.rename_website(1, WebsiteRename(new_domain="new.test"), request=None, db=db,
                                current_user=User(id=9, role="admin"))
    except websites.HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected the rename to fail when the vhost cannot be written")
    assert website.domain == "old.test"
    assert website.root_path == "/home/alice/old.test"
    assert calls["move"][-1] == ("/home/alice/new.test", "/home/alice/old.test", "alice", None)
