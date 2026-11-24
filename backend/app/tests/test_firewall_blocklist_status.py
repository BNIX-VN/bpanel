"""firewall-blocklist-status prints the whole report for a large blocklist.

It listed the first 50 networks with `sed | head -n 50`: head exited while sed
was still writing, sed died of SIGPIPE, pipefail turned that into exit 141 and
set -e stopped the helper mid-listing. The Firewall page got a cut-off report
(1641 networks on .88, 2026-11-24).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


def _function(name: str) -> str:
    body = HELPER[HELPER.index(f"\n{name}() {{") + 1:]
    return body[:body.index("\n}\n") + 3]


def test_the_listing_does_not_close_a_pipe_early():
    code = "\n".join(
        line for line in _function("firewall_blocklist_status").splitlines() if not line.strip().startswith("#")
    )
    assert "| head" not in code


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_a_large_blocklist_reports_in_full(tmp_path):
    work = tmp_path / "blocklist.work"
    lines = [f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}/32" for i in range(200000)]
    lines.insert(3, "   ")  # a blank line is not a network
    work.write_text("\n".join(lines) + "\n", encoding="utf-8")
    urls = tmp_path / "urls"
    urls.write_text("https://example.test/list.txt\n", encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'FIREWALL_BLOCKLIST_WORK="{work.as_posix()}"\n'
        f'FIREWALL_BLOCKLIST_URLS="{urls.as_posix()}"\n'
        "ensure_firewall_dir() { :; }\n"
        'firewall_blocklist_urls() { cat "$FIREWALL_BLOCKLIST_URLS"; }\n'
        "firewall_set_count() { echo 200000; }\n"
        "firewall_has_ipv6() { return 1; }\n"
        'systemctl() { echo "systemctl $*"; }\n'
        + _function("firewall_blocklist_status")
        + "firewall_blocklist_status\n"
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, (result.returncode, result.stderr)
    out = result.stdout
    assert "  200000 network(s), showing first 50:" in out
    listed = [line for line in out.splitlines() if line.startswith("  10.")]
    assert len(listed) == 50 and listed[0] == "  10.0.0.0/32"
    assert "  ... 199950 more" in out
    assert "Timer:" in out
