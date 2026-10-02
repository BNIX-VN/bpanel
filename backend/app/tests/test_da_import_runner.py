"""The detached DirectAdmin import runs, and the page learns how it ended.

On .88 every import died on its first line: the runner, started as a script,
had app/services first on sys.path, so its ssl.py stood in for the standard
library's. The page then polled "unknown" for half an hour, because the unit
had been unloaded by the time anyone asked how it went (2026-10-02).
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import maintenance
from app.core.permissions import Role
from app.services import da_import

BACKEND = Path(__file__).resolve().parents[2]
RUNNER = BACKEND / "app" / "services" / "da_import_run.py"
HELPER = BACKEND.parent / "installer" / "files" / "bpanel-helper.sh"


def test_the_runner_started_as_a_script_gets_the_real_ssl_module(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "DA_IMPORT_STAGE_BASE": str(tmp_path / "stage"),
        "BPANEL_DA_BACKUP_DIR": str(tmp_path / "da"),
        "INVOCATION_ID": "a" * 32,
    }
    # The way the helper starts it: the script's path, not -m.
    done = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path / "elsewhere.tar.zst"), "noforce"],
        env=env, capture_output=True, text=True, timeout=120,
    )
    record = json.loads((tmp_path / "stage" / "last-import.json").read_text(encoding="utf-8"))
    # It got as far as the import itself, which refused the path: da_import and
    # everything under it - fastapi, anyio, ssl - imported.
    assert "SSLContext" not in done.stdout + done.stderr
    assert record["status"] == "failed", done.stdout + done.stderr
    assert "Backup must be inside" in record["error"]
    assert record["invocation"] == "a" * 32 and record["archive"] == "elsewhere.tar.zst"
    assert done.returncode == 1
    if os.name == "posix":
        # It holds the generated passwords of a successful import.
        assert (tmp_path / "stage" / "last-import.json").stat().st_mode & 0o077 == 0


def test_the_runner_and_the_panel_agree_on_the_record_file():
    from app.services import da_import_run

    assert Path(da_import_run.RESULT_FILE) == da_import.IMPORT_RESULT_FILE


def test_a_finished_import_does_not_put_its_passwords_in_the_journal():
    source = RUNNER.read_text(encoding="utf-8")
    assert 'print(f"RESULT: {result}' not in source
    assert "write_record({**record, \"status\": \"completed\", \"result\": result" in source


def test_a_failed_run_stays_loaded_for_the_status_to_read():
    start = HELPER.read_text(encoding="utf-8").split("start_da_import() {", 1)[1].split("\n}\n", 1)[0]
    code = "\n".join(line for line in start.splitlines() if not line.strip().startswith("#"))
    assert "systemd-run" in code
    assert "--collect" not in code


def _status(monkeypatch, tmp_path, helper_output, record=None):
    result_file = tmp_path / "last-import.json"
    if record is not None:
        result_file.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(da_import, "IMPORT_RESULT_FILE", result_file)
    monkeypatch.setattr(da_import.shell, "privileged",
                        lambda *args, **kwargs: SimpleNamespace(stdout=helper_output, returncode=0))
    return da_import.detached_import_status()


COLLECTED = "active=inactive\nresult=success\nexit=0\ninvocation=\n---log---\n"
SUMMARY = {"summary": [{"username": "e2", "imported_domains": ["e2.vn"]}], "credentials": ["x"], "errors": []}


def test_a_run_systemd_has_forgotten_is_read_from_its_record(monkeypatch, tmp_path):
    info = _status(monkeypatch, tmp_path, COLLECTED, {
        "invocation": "b" * 32, "archive": "user.admin.e2.tar.zst", "status": "completed", "result": SUMMARY,
    })
    assert info["status"] == "completed"
    assert info["import_result"] == SUMMARY
    assert info["invocation"] == "b" * 32 and info["archive"] == "user.admin.e2.tar.zst"


def test_a_failure_is_reported_with_its_reason(monkeypatch, tmp_path):
    info = _status(monkeypatch, tmp_path, COLLECTED, {
        "invocation": "b" * 32, "status": "failed", "error": "Backup not found: x.tar.zst",
    })
    assert info["status"] == "failed" and info["error"] == "Backup not found: x.tar.zst"


def test_a_record_left_at_running_means_the_process_died(monkeypatch, tmp_path):
    info = _status(monkeypatch, tmp_path, COLLECTED, {"invocation": "b" * 32, "status": "running"})
    assert info["status"] == "failed" and "stopped before it finished" in info["error"]


def test_a_running_unit_is_running_whatever_an_older_record_says(monkeypatch, tmp_path):
    output = "active=active\nresult=success\nexit=0\ninvocation=" + "c" * 32 + "\n---log---\n"
    info = _status(monkeypatch, tmp_path, output, {"invocation": "b" * 32, "status": "completed", "result": SUMMARY})
    assert info["status"] == "running"
    assert info["invocation"] == "c" * 32 and info["import_result"] is None


def test_a_unit_that_died_before_writing_a_record_fails_with_its_log(monkeypatch, tmp_path):
    output = (
        "active=failed\nresult=exit-code\nexit=1\ninvocation=" + "c" * 32 + "\n---log---\n"
        "Started bpanel-da-import.service - old run\nRESULT: 1 account(s), 1 domain(s), 0 error(s)\n"
        "Started bpanel-da-import.service - this run\n"
        "Traceback (most recent call last):\n"
        "ImportError: cannot import name 'SSLContext' from 'ssl'\n"
        "bpanel-da-import.service: Main process exited, code=exited, status=1/FAILURE\n"
    )
    info = _status(monkeypatch, tmp_path, output, {"invocation": "b" * 32, "status": "completed", "result": SUMMARY})
    assert info["status"] == "failed"
    assert info["error"].startswith("ImportError: cannot import name 'SSLContext'")
    # Only this run's lines.
    assert info["log"][0] == "Started bpanel-da-import.service - this run"
    assert not any(line.startswith("RESULT:") for line in info["log"])


def test_nothing_to_go_on_is_unknown(monkeypatch, tmp_path):
    assert _status(monkeypatch, tmp_path, COLLECTED)["status"] == "unknown"
    # The helper did not answer: a record that says "running" may well be true.
    info = _status(monkeypatch, tmp_path, "active=unknown\n", {"invocation": "b" * 32, "status": "running"})
    assert info["status"] == "unknown"


@pytest.fixture
def admin():
    return SimpleNamespace(role=str(Role.admin), id=1)


def test_the_page_gets_the_summary_of_its_own_import_only(monkeypatch, admin):
    info = {"status": "completed", "invocation": "b" * 32, "archive": "e2.tar.zst", "error": "",
            "log": [], "import_result": SUMMARY}
    monkeypatch.setattr(da_import, "detached_import_status", lambda: dict(info))
    mine = maintenance.get_da_import_job("b" * 32, current_user=admin)
    assert mine["status"] == "completed" and mine["result"] == SUMMARY and mine["archive"] == "e2.tar.zst"

    other = maintenance.get_da_import_job("d" * 32, current_user=admin)
    assert other["stale"] is True and other["status"] == "unknown" and other["result"] is None
