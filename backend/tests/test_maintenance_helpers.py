import os
import sys

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("COMMAND_DRY_RUN", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ""))

from app.services import cron, firewall  # noqa: E402


def test_cron_line_parser_strips_bpanel_wrapper():
    item = cron._parse_cron_line(0, "*/15 * * * * cd /home/admin/example.com/public_html && wp cron event run --due-now --allow-root # bpanel:example.com")  # noqa: SLF001

    assert item["index"] == 0
    assert item["schedule"] == "*/15 * * * *"
    assert item["command"] == "wp cron event run --due-now"


def test_firewall_numbered_rules_mark_defaults_protected(monkeypatch):
    monkeypatch.setattr(firewall.settings, "panel_port", 2222)

    rules = firewall.parse_numbered_rules(
        "[ 1] 22/tcp                     ALLOW IN    Anywhere\n"
        "[ 2] 2222/tcp                   ALLOW IN    Anywhere\n"
        "[ 3] 5.6.7.8                    DENY IN     Anywhere"
    )

    assert [rule["number"] for rule in rules] == [1, 2, 3]
    assert rules[0]["protected"] is True
    assert rules[1]["protected"] is True
    assert rules[2]["protected"] is False
