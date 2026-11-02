"""Deleting a website drops the cron lines the panel wrote for it, and only those."""
from app.services import cron

CRONTAB = "\n".join([
    "MAILTO=\"\"",
    "*/5 * * * * cd /home/alice/a.com/public_html && php job.php # bpanel:a.com",
    "0 3 * * * cd /home/alice/a.com.vn/public_html && php job.php # bpanel:a.com.vn",
    "15 * * * * cd /home/alice/b.com/public_html && php job.php # BPANEL:b.com",
    "0 * * * * /home/alice/bin/backup.sh",
    "30 * * * * cd /home/alice/a.com/public_html && php wp-cron.php # bpanel:a.com",
])


def _run(monkeypatch, crontab, domain):
    written = []
    monkeypatch.setattr(cron, "list_cron_all", lambda user: crontab)
    monkeypatch.setattr(cron.shell, "privileged",
                        lambda name, helper_args=None, input=None, **kw: written.append((name, helper_args, input)))
    return cron.remove_website_cron(domain, "alice"), written


def test_removes_only_the_sites_own_lines(monkeypatch):
    removed, written = _run(monkeypatch, CRONTAB, "a.com")
    assert removed == 2
    (name, args, content), = written
    assert (name, args) == ("cron-write", ["alice"])
    assert "# bpanel:a.com\n" not in content and not content.rstrip().endswith("# bpanel:a.com")
    # A longer domain sharing the prefix, another site, and a hand-written job stay.
    assert "# bpanel:a.com.vn" in content
    assert "# BPANEL:b.com" in content
    assert "/home/alice/bin/backup.sh" in content
    assert content.startswith("MAILTO=")


def test_marker_case_does_not_matter(monkeypatch):
    removed, written = _run(monkeypatch, CRONTAB, "b.com")
    assert removed == 1
    assert "b.com" not in written[0][2]


def test_nothing_to_remove_leaves_the_crontab_alone(monkeypatch):
    removed, written = _run(monkeypatch, CRONTAB, "c.com")
    assert removed == 0
    assert written == []
