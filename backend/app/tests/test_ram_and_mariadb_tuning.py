"""Where the RAM is, and MariaDB sized for a hosting server (operator,
2026-10-06, after an OPanel server collapsed under load).

An account's RAM is its cgroup's memory.current: its processes plus their file
cache, OPcache's shared memory included. MariaDB serves every site, so it is in
no account; the dashboard now says so with numbers. MariaDB itself takes a
quarter of the RAM at most and no more than its data needs, its connections
follow the PHP-FPM workers, and an update restarts it only when a setting
changed.
"""
from pathlib import Path

from app.services import system

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT = (PROJECT_ROOT / "backend" / "app" / "agents" / "bpanel_limits_agent.py").read_text(encoding="utf-8")
APP = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


def _cgroup(root: Path, relative: str, current_mb: int, file_mb: int, shmem_mb: int, anon_mb: int) -> None:
    folder = root / relative
    folder.mkdir(parents=True)
    mb = 1048576
    (folder / "memory.current").write_text(f"{current_mb * mb}\n")
    (folder / "memory.stat").write_text(f"anon {anon_mb * mb}\nfile {file_mb * mb}\nshmem {shmem_mb * mb}\nkernel 0\n")


def test_the_parts_add_up_to_the_total(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "CGROUP_ROOT", tmp_path)
    mb = 1048576
    _cgroup(tmp_path, "hosting.slice", current_mb=2300, file_mb=700, shmem_mb=300, anon_mb=1600)
    _cgroup(tmp_path, "system.slice/mariadb.service", current_mb=2150, file_mb=40, shmem_mb=0, anon_mb=2110)
    total, available, free = 15986 * mb, 10214 * mb, 7883 * mb
    parts = system._memory_breakdown(total, available, free)
    assert parts["accounts"] == 1900 * mb, "the clean file cache in the accounts is not counted twice"
    assert parts["mariadb"] == 2110 * mb
    assert parts["cache"] == (10214 - 7883) * mb and parts["free"] == 7883 * mb
    assert sum(parts.values()) == total


def test_without_the_addon_there_is_no_accounts_part(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "CGROUP_ROOT", tmp_path)
    parts = system._memory_breakdown(4096, 2048, 1024)
    assert parts["accounts"] is None and parts["mariadb"] is None
    assert parts["system"] + parts["cache"] + parts["free"] == 4096


def test_the_agent_reports_what_an_accounts_ram_is_made_of():
    counters = AGENT.split("def counters(slice_name):", 1)[1].split("\ndef ", 1)[0]
    assert '"memory_anon": stat.get("anon", 0)' in counters and '"memory_file": stat.get("file", 0)' in counters
    sample = AGENT.split("    def sample(self, config):", 1)[1].split("\n    def ", 1)[0]
    assert '"memory_anon_mb": current["memory_anon"] // 1048576' in sample
    assert '"memory_cache_mb": current["memory_file"] // 1048576' in sample


def test_the_pages_say_it():
    assert "<RamBreakdown memory={memory} />" in APP
    assert "now.memory_anon_mb != null" in APP


def test_mariadb_is_sized_for_a_hosting_server():
    calc = HELPER.split("\ncalculate_mariadb_tuning() {", 1)[1].split("\n}\n", 1)[0]
    assert "buffer_default=$((total_mb * 25 / 100))" in calc
    assert "local wanted=$((data_mb * 5 / 4))" in calc
    assert 'php_workers="$(php_fpm_children_total)"' in calc
    assert "max_connections=$((php_workers + 20))" in calc
    assert "tmp_mb=64" in calc and "tmp_mb=32" in calc
    assert "36 / 100" not in calc and "tmp_mb=128" not in calc
    children = HELPER.split("\nphp_fpm_children_total() {", 1)[1].split("\n}\n", 1)[0]
    assert "/etc/php/*/fpm/pool.d/bpanel-*.conf" in children and "pm\\.max_children" in children


def test_an_update_restarts_mariadb_only_when_a_setting_changed():
    write = HELPER.split("\nwrite_mariadb_tuning() {", 1)[1].split("\n}\n", 1)[0]
    assert 'cmp -s "$staged" "$MARIADB_TUNING_CONF"' in write
    retune = HELPER.split("\nretune_mariadb() {", 1)[1].split("\n}\n", 1)[0]
    assert retune.index("if write_mariadb_tuning; then") < retune.index("systemctl restart mariadb")
