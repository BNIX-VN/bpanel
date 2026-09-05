from app.api import websites
from app.models.entities import User, Website, WebsiteAlias
from app.schemas.schemas import WebsiteAliasCreate


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, website):
        self.website = website
        self.aliases = []
        self.added = []
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        if model is Website:
            return _Query([self.website])
        if model is WebsiteAlias:
            return _Query(self.aliases)
        return _Query([])

    def add(self, item):
        self.added.append(item)
        if isinstance(item, WebsiteAlias):
            item.id = len(self.aliases) + 1
            item.website = self.website
            self.aliases.append(item)
            self.website.aliases = [*getattr(self.website, "aliases", []), item]

    def flush(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, item):
        pass


def test_create_alias_expands_letsencrypt_certificate(monkeypatch):
    website = Website(
        id=1,
        domain="example.test",
        owner_id=1,
        root_path="/home/bp_example_test/example.test",
        linux_user=None,
        ssl_enabled=True,
        ssl_mode="letsencrypt",
    )
    website.aliases = [WebsiteAlias(domain="old.example.test", mode="redirect")]
    db = _Db(website)
    issued = []

    monkeypatch.setattr(websites, "_rewrite_website_vhost", lambda *args, **kwargs: "/etc/nginx/conf.d/example.test.conf")
    monkeypatch.setattr(websites.ssl, "issue_ssl", lambda domain, aliases: issued.append((domain, aliases)) or type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(websites.ssl, "cert_info", lambda domain: {"sans": ["example.test", "old.example.test", "alias.example.test"]})
    monkeypatch.setattr(websites, "log_action", lambda *args, **kwargs: None)

    alias = websites.create_website_alias(
        1,
        WebsiteAliasCreate(domain="Alias.Example.Test"),
        request=None,
        db=db,
        current_user=User(id=1, role="admin"),
    )

    assert alias.domain == "alias.example.test"
    assert db.committed is True
    assert db.rolled_back is False
    assert issued == [("example.test", ["alias.example.test", "old.example.test"])]
    assert alias.ssl_enabled is True


def test_create_alias_reports_when_dns_does_not_point_here_yet(monkeypatch):
    # issue_ssl() can succeed overall while dropping this exact domain
    # (--allow-subset-of-names, e.g. DNS not pointed here yet) - the alias is
    # still created (nginx does serve it), but ssl_enabled must say so rather
    # than a blanket "added" implying it also got working SSL.
    website = Website(
        id=1, domain="example.test", owner_id=1,
        root_path="/home/bp_example_test/example.test", linux_user=None,
        ssl_enabled=True, ssl_mode="letsencrypt",
    )
    website.aliases = []
    db = _Db(website)

    monkeypatch.setattr(websites, "_rewrite_website_vhost", lambda *args, **kwargs: "/etc/nginx/conf.d/example.test.conf")
    monkeypatch.setattr(websites.ssl, "issue_ssl", lambda domain, aliases: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    # The certificate exists, but does not (yet) cover the new alias.
    monkeypatch.setattr(websites.ssl, "cert_info", lambda domain: {"sans": ["example.test"]})
    monkeypatch.setattr(websites, "log_action", lambda *args, **kwargs: None)

    alias = websites.create_website_alias(
        1,
        WebsiteAliasCreate(domain="not-pointed.example.test"),
        request=None,
        db=db,
        current_user=User(id=1, role="admin"),
    )

    assert alias.domain == "not-pointed.example.test"
    assert alias.ssl_enabled is False
    assert db.committed is True


def test_enabling_ssl_wires_up_an_existing_redirect_domain(monkeypatch):
    # A redirect-domain alias has no server block of its own until this runs
    # (see nginx._append_certbot_redirect_vhosts) - reported live on a
    # DirectAdmin-imported site whose redirect pointer predated SSL being
    # turned on: the certificate covered it once issue_ssl() started asking
    # for every alias, but nothing ever re-rendered the vhost to give it a
    # 443 block reusing that certificate, so it still had no working SSL.
    website = Website(
        id=1, domain="example.test", owner_id=1,
        root_path="/home/bp_example_test/example.test", linux_user=None,
        ssl_enabled=False, ssl_mode="none",
    )
    website.aliases = [WebsiteAlias(domain="old.example.test", mode="redirect")]
    db = _Db(website)
    rewritten = []

    monkeypatch.setattr(websites, "_block_if_source", lambda *a, **k: None)
    monkeypatch.setattr(websites, "_resync_shared_dependents", lambda *a, **k: None)
    monkeypatch.setattr(websites, "_rewrite_website_vhost", lambda site, **kw: rewritten.append(site) or "/etc/nginx/conf.d/example.test.conf")
    monkeypatch.setattr(websites.ssl, "issue_ssl", lambda domain, aliases: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(websites, "log_action", lambda *args, **kwargs: None)

    websites.enable_ssl(1, db=db, current_user=User(id=1, role="admin"))

    assert website.ssl_mode == "letsencrypt"
    assert rewritten == [website]


def test_enabling_ssl_skips_the_rewrite_with_no_redirect_domains(monkeypatch):
    website = Website(
        id=1, domain="example.test", owner_id=1,
        root_path="/home/bp_example_test/example.test", linux_user=None,
        ssl_enabled=False, ssl_mode="none",
    )
    website.aliases = []
    db = _Db(website)
    rewritten = []

    monkeypatch.setattr(websites, "_block_if_source", lambda *a, **k: None)
    monkeypatch.setattr(websites, "_resync_shared_dependents", lambda *a, **k: None)
    monkeypatch.setattr(websites, "_rewrite_website_vhost", lambda site, **kw: rewritten.append(site) or "/etc/nginx/conf.d/example.test.conf")
    monkeypatch.setattr(websites.ssl, "issue_ssl", lambda domain, aliases: type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(websites, "log_action", lambda *args, **kwargs: None)

    websites.enable_ssl(1, db=db, current_user=User(id=1, role="admin"))

    assert rewritten == []
