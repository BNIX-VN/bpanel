"""A port-only firewall rule ("open 8080 to everyone") must load.

rules.tsv has an empty ip column for such a rule. The helper read it with
IFS=$'\\t', but tab is whitespace to `read`, so the empty column collapsed:
"120<TAB>allow<TAB><TAB>8080<TAB>tcp" became ip=8080, port=tcp. The ipset
entry "8080,:tcp" was refused, and every firewall change on .88 failed with
"Internal server error" from then on (2026-10-03). The rule never opened the
port either: the chain builder skipped it as an ip rule.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

HELPER = (Path(__file__).resolve().parents[3] / "installer" / "files" / "bpanel-helper.sh").read_text(
    encoding="utf-8")


def test_no_rules_loop_reads_with_tab_as_the_separator():
    assert "IFS=$'\\t' read" not in HELPER


def _body(name):
    return HELPER.split(f"{name}() {{", 1)[1].split("\n}\n", 1)[0]


def test_every_rules_loop_turns_tabs_into_the_unit_separator():
    sync = _body("firewall_sync_sets")
    assert "while IFS=$'\\037' read -r _id action ip port protocol; do" in sync
    assert "done < <(tr '\\t' '\\037' <<<\"$rules\")" in sync
    assert "done < <(firewall_rules | tr '\\t' '\\037')" in HELPER
    assert "' | tr '\\t' '\\037')" in _body("firewall_import_ufw_rules")


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("line, fields", [
    ("120\tallow\t\t8080\ttcp", "[120][allow][][8080][tcp]"),
    ("118\tallow\t42.119.36.12/32\t\t", "[118][allow][42.119.36.12/32][][]"),
    ("7\tdeny\t10.0.0.0/8\t3306\ttcp", "[7][deny][10.0.0.0/8][3306][tcp]"),
])
def test_the_unit_separator_keeps_empty_columns(line, fields):
    script = (
        "printf '%s\\n' \"$1\" | tr '\\t' '\\037' | "
        "while IFS=$'\\037' read -r id action ip port proto; do "
        "printf '[%s][%s][%s][%s][%s]' \"$id\" \"$action\" \"$ip\" \"$port\" \"$proto\"; done"
    )
    out = subprocess.run(["bash", "-c", script, "bash", line], capture_output=True, text=True, check=True)
    assert out.stdout == fields
