"""clamscan and clamd load a copy of ClamAV's signatures filtered by clam-juice.

Measured 2026-09-30: of the 3.6 million signatures in main and daily, all but
131 thousand are Windows, macOS or Office malware. A clamscan loaded them all
-- about 1 GB and 24 s before the first file; on .88 Level 2 without clamd
kept one running 103 of every 293 seconds, peaking at 1043 MB. The filtered
set loads in 1.6 s in 180 MB. The operator asked for
github.com/swelljoe/clam-juice, as in OPanel.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELPER = (ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
UPDATE = (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")


def _function(name: str) -> str:
    return HELPER.split(f"\n{name}() {{", 1)[1].split("\n}\n", 1)[0]


def _command(name: str) -> str:
    return HELPER.split(f"\n  {name})\n", 1)[1].split("\n    ;;\n\n", 1)[0]


def _value(name: str) -> str:
    return HELPER.split(f"\n{name}=", 1)[1].split("\n", 1)[0].strip('"')


def test_clam_juice_is_pinned_and_checked_before_it_is_installed():
    commit, digest = _value("CLAMJUICE_COMMIT"), _value("CLAMJUICE_SHA256")
    assert len(commit) == 40 and int(commit, 16) >= 0
    assert len(digest) == 64 and int(digest, 16) >= 0
    body = _function("install_clamjuice")
    assert "raw.githubusercontent.com/swelljoe/clam-juice/${CLAMJUICE_COMMIT}/clam_juice.py" in body
    assert body.index('!= "$CLAMJUICE_SHA256"') < body.index('install -o root -g root -m 0755 "$tmp" "$CLAMJUICE_BIN"')


def test_it_drops_windows_macos_and_office_but_keeps_what_a_web_server_needs():
    args = HELPER.split("\nCLAMJUICE_ARGS=(", 1)[1].split(")", 1)[0].split()
    platforms = set(args[args.index("--exclude-platforms") + 1].split(","))
    assert platforms == {"Win", "Osx", "Doc", "Xls", "Ppt", "Rtf"}
    assert "mdb" in args[args.index("--exclude-types") + 1].split(",")
    ndb = set(args[args.index("--ndb-types") + 1].split(","))
    # HTML (3) and ELF (6) stay; PE (1) and OLE2 (2) go.
    assert {"0", "3", "6", "7"} <= ndb and not {"1", "2"} & ndb


def test_the_set_lives_where_clamd_may_read_and_scans_do_not_look():
    # Ubuntu's AppArmor profile for clamd allows /var/lib/clamav/** only.
    assert _value("CLAMAV_FILTERED_DIR") == "${CLAMAV_DB_DIR}/bpanel-filtered"
    assert _value("CLAMAV_DB_DIR") == "/var/lib/clamav"
    assert "/var/lib/clamav" in HELPER.split("\nMALWARE_SCAN_PRUNE=(", 1)[1].split(")", 1)[0]
    assert "  /var/lib/clamav\n" in HELPER.split("\nMALDET_IGNORE_PATHS=(", 1)[1].split(")", 1)[0]


def test_a_new_set_is_test_scanned_as_strictly_as_clamd_before_anything_uses_it():
    build = _function("clamav_filter_build")
    assert build.index('-d "$gen" "${work}/eicar.txt"') < build.index('mv -Tf "${CLAMAV_FILTERED_DIR}/current.new"')
    assert '[[ "$rc" -ne 1' in build  # it must detect the test file
    assert 'clamscan "${scan_opts[@]}" -d "$gen"' in build
    options = _function("clamd_matching_scan_options")
    assert "FIPSCryptoHashLimits" in options and 'echo "--fips-limits"' in options
    # ClamAV 1.5 needs a copied .cvd's detached signature beside it.
    assert "done < <(clamav_extra_dbs; clamav_detached_signatures)" in build
    assert build.index('rm -f -- "$gen"/*.cdiff "$gen"/*.sign') < build.index("clamav_detached_signatures")
    assert 'TMPDIR="$work"' in build
    assert "if (( n > 2 )); then rm -rf" in build


def test_this_script_is_not_a_test_file_to_the_scanners_that_read_it():
    eicar = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-" + "ANTIVIRUS-TEST-FILE!$H+H*"
    assert eicar not in HELPER
    assert "EICAR-STANDARD-' 'ANTIVIRUS-TEST-FILE" in HELPER


def test_the_totals_are_read_from_clam_juices_report():
    script = _function("clamjuice_totals").split("awk '", 1)[1].rsplit("'", 1)[0]
    report = (
        "\n.LDB files:\n  Original:      38,889 signatures\n  Filtered:       4,000 signatures\n"
        "\n======\nTOTAL:\n  Original:   3,286,543 signatures\n"
        "  Filtered:      88,356 signatures (  2.7%)\n  Removed:   3,198,187 signatures\n"
    )
    out = subprocess.run(["awk", script], input=report, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["3286543", "88356"]


def _run_lmd_switch(tmp_path, *steps):
    """Runs the helper's lmd_use_filtered_set on a copy of maldet's files."""
    maldet = tmp_path / "maldetect"
    (maldet / "internals").mkdir(parents=True, exist_ok=True)
    clamav = tmp_path / "clamav"
    clamav.mkdir(exist_ok=True)
    script = "\n".join([
        "set -euo pipefail",
        f"MALDET_HOME={maldet.as_posix()}",
        f"MALDET_CONF={maldet.as_posix()}/conf.maldet",
        f"CLAMAV_DB_DIR={clamav.as_posix()}",
        f"CLAMAV_FILTERED_DIR={clamav.as_posix()}/bpanel-filtered",
        f"CLAMAV_FILTERED_CURRENT={clamav.as_posix()}/bpanel-filtered/current",
        f"CLAMAV_FILTERED_LMD_DIR={clamav.as_posix()}/bpanel-filtered/lmd",
        f"mkdir -p {clamav.as_posix()}/bpanel-filtered",
        "install() { mkdir -p \"${@: -1}\"; }",
        "lmd_internals_set() {" + _function("lmd_internals_set") + "\n}",
        "lmd_use_filtered_set() {" + _function("lmd_use_filtered_set") + "\n}",
        *[f"if lmd_use_filtered_set {step}; then echo changed; else echo same; fi" for step in steps],
    ])
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.split(), maldet / "internals" / "internals.conf", clamav


def test_maldet_hands_clamscan_the_filtered_set_and_no_full_one(tmp_path):
    """maldet adds -d for the last clamav_paths directory holding main.cvd -- the
    full set. Pointing clamav_paths at a directory without one drops that, and
    clamscan_extraopts adds the filtered set. In internals.conf, not
    conf.maldet: the Level 2 monitor re-reads internals.conf last every hour."""
    stock_paths = ('clamav_paths="/usr/local/cpanel/3rdparty/share/clamav/ /var/lib/clamav/ '
                   '/var/clamav/ /usr/share/clamav/ /usr/local/share/clamav"')
    internals = tmp_path / "maldetect" / "internals" / "internals.conf"
    internals.parent.mkdir(parents=True)
    internals.write_text(f'inspath=/usr/local/maldetect\nclamscan_extraopts=""\n{stock_paths}\n', encoding="utf-8")
    (tmp_path / "maldetect" / "conf.maldet").write_text(
        'scan_clamscan="1"\nclamav_paths="/old/"\n', encoding="utf-8")
    clamav = tmp_path / "clamav"
    clamav.mkdir()
    (clamav / "rfxn.yara").write_text("rule x {}", encoding="utf-8")

    results, internals, clamav = _run_lmd_switch(tmp_path, "on", "on")
    assert results == ["changed", "same"]  # the monitor restarts once, not every run
    text = internals.read_text(encoding="utf-8")
    assert f'clamav_paths="{clamav.as_posix()}/bpanel-filtered/lmd/"' in text
    assert f'clamscan_extraopts="-d {clamav.as_posix()}/bpanel-filtered/current"' in text
    # maldet's own copy moved with it; the first version's conf.maldet key is gone.
    assert (clamav / "bpanel-filtered" / "lmd" / "rfxn.yara").is_file() and not (clamav / "rfxn.yara").exists()
    assert "clamav_paths" not in (tmp_path / "maldetect" / "conf.maldet").read_text(encoding="utf-8")

    results, internals, clamav = _run_lmd_switch(tmp_path, "off", "off")
    assert results == ["changed", "same"]
    text = internals.read_text(encoding="utf-8")
    assert stock_paths in text and 'clamscan_extraopts=""' in text
    assert (clamav / "rfxn.yara").is_file()


def test_the_monitor_restarts_onto_the_set_and_reloads_off_it():
    # maldet never clears the -d it chose at start: a reload alone would load both.
    run = _function("clamav_filter_run")
    assert "if lmd_use_filtered_set on && systemctl is-active --quiet maldet" in run
    assert "systemctl restart maldet" in run
    use_full = _function("clamav_filter_use_full")
    assert 'touch "${MALDET_HOME}/reload_monitor"' in use_full
    # maldet's copies are part of the set, compared by content: it rewrites them
    # before every scan.
    assert '"$CLAMAV_FILTERED_LMD_DIR"/*' in _function("clamav_extra_dbs")
    assert 'sha256sum <"$f"' in _function("clamav_filter_fingerprint")


def test_maldet_signature_updates_reach_the_set():
    # The path unit watches freshclam's directory, not maldet's copies.
    assert "PathChanged=/var/lib/clamav\n" in HELPER
    assert "PathChanged=/var/lib/clamav/bpanel-filtered" not in HELPER
    assert "clamav_filter_run_locked" in _command("maldet-update-sigs")


def test_clamd_follows_and_falls_back_when_it_does_not_come_up():
    run = _function("clamav_filter_run")
    assert 'clamd_set_database_dir "$CLAMAV_FILTERED_CURRENT"; then\n    if clamd_apply restart; then' in run
    assert "elif (( changed )); then\n    if clamd_apply reload; then" in run
    fallback = run.split("# A scanner that does not run", 1)[1]
    assert '"${CLAMAV_FILTERED_DIR}/failed"' in fallback and "clamav_filter_use_full" in fallback
    use_full = _function("clamav_filter_use_full")
    assert "lmd_use_filtered_set off" in use_full and 'rm -f "$CLAMAV_FILTER_IN_USE"' in use_full
    assert 'clamd_set_database_dir "$CLAMAV_DB_DIR"' in use_full
    ready = _function("clamd_wait_ready")
    assert ready.index("systemctl is-active") < ready.index("clamdscan --ping 1")
    # Only a server with clamd has a clamd.conf to change.
    assert "pkg_installed clamav-daemon || return 1" in _function("clamd_set_database_dir")
    # A daemon installed later is moved onto the set.
    assert "clamav_filter_run_locked" in _function("install_clamav_daemon")


def test_installs_filter_and_every_update_brings_it_unless_turned_off():
    assert "clamav_filter_setup" in _function("install_clamav_engine")
    maldet = _function("install_maldet_engine")
    assert maldet.index('"$MALDET_BIN" -u --force') < maldet.index("clamav_filter_setup")
    assert "clamav-filter ensure" in UPDATE and "pkg_installed clamav; then" in UPDATE
    ensure = _function("ensure_clamav_filter")
    assert '"$CLAMAV_FULL_DB_MARKER"' in ensure
    assert "systemctl start --no-block bpanel-clamav-filter.service" in ensure
    command = _command("clamav-filter")
    assert 'touch "$CLAMAV_FULL_DB_MARKER"' in command
    disable = _function("clamav_filter_disable")
    assert disable.index("clamav_filter_use_full") < disable.index('rm -rf -- "$CLAMAV_FILTERED_DIR"')
    # No loop: an existing directory is not chmod-ed again.
    assert 'if [[ ! -d "$CLAMAV_FILTERED_DIR" ]]; then\n    install -d' in _function("clamav_filter_build")
    assert "flock -w 900 9" in _function("clamav_filter_run_locked")


def test_the_panels_own_clamscan_uses_the_set(monkeypatch, tmp_path):
    from app.services import malware_scan

    monkeypatch.setattr(malware_scan, "FILTERED_DB_DIR", str(tmp_path))
    monkeypatch.setattr(malware_scan, "FILTER_PATH_UNIT", str(tmp_path / "unit.path"))
    assert malware_scan.filtered_database() is None
    assert malware_scan.signature_filter_status()["signature_filter"] == "off"
    (tmp_path / "unit.path").write_text("")
    assert malware_scan.signature_filter_status()["signature_filter"] == "pending"
    (tmp_path / "current").mkdir()
    (tmp_path / "in-use").write_text("")
    (tmp_path / "stats").write_text("kept=131338 total=3626588 loaded=232212\n")
    assert malware_scan.filtered_database() == str(tmp_path / "current")
    status = malware_scan.signature_filter_status()
    assert status == {"signature_filter": "on", "signatures_kept": 131338, "signatures_total": 3626588}

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(malware_scan.subprocess, "run", fake_run)
    malware_scan._scan_file_clamscan("/home/site/upload.php")
    assert seen["command"] == ["clamscan", "--infected", "--no-summary", "-d", str(tmp_path / "current"),
                               "/home/site/upload.php"]


def test_a_2_gb_server_is_not_warned_once_the_set_is_filtered():
    from app.services import malware_scan

    assert malware_scan.memory_warning(1855)
    assert malware_scan.memory_warning(1855, filtered=True) == ""
    warning = malware_scan.memory_warning(960, filtered=True)
    assert "960" in warning and "about 200 MB" in warning
