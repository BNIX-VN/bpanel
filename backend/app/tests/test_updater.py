"""The updater must apply its own changes in the run that brings them in.

bash reads a script as it runs, so update.sh re-execs a copy of itself from
/tmp - a copy of the *previous* release. Without a handover, anything an update
changes about updating itself lands one release late, which is how a server
once kept running the old panel start-up script after the release that replaced
it.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = PROJECT_ROOT / "installer" / "update.sh"


def _script() -> str:
    return UPDATE_SCRIPT.read_text(encoding="utf-8")


def _handover_block() -> str:
    script = _script()
    start = script.index("# bash reads a script as it runs")
    return script[start : script.index("# --- Sync code into APP_DIR")]


def test_the_updater_hands_over_to_the_one_from_the_new_release():
    block = _handover_block()
    assert 'exec /bin/bash "$stage2_copy"' in block
    assert 'cp "$SOURCE_DIR/installer/update.sh" "$stage2_copy"' in block
    # Only when it actually differs, so an unchanged updater keeps going.
    assert 'cmp -s "$SOURCE_DIR/installer/update.sh"' in block


def test_the_handover_cannot_loop():
    block = _handover_block()
    assert '[[ -z "${BPANEL_UPDATE_STAGE2:-}"' in block
    assert "BPANEL_UPDATE_STAGE2=1" in block


def test_the_second_stage_does_not_fetch_the_release_again():
    block = _handover_block()
    assert "SKIP_PULL=true" in block
    assert 'SOURCE_DIR="$SOURCE_DIR"' in block
    # The release name has to survive, or the panel would report the update as
    # coming from a temporary directory.
    assert 'BPANEL_UPDATE_REF_OVERRIDE="${UPDATE_REF:-}"' in _handover_block()
    assert 'UPDATE_REF="${BPANEL_UPDATE_REF_OVERRIDE:-local:${SOURCE_DIR}}"' in _script()


def test_the_handover_leaves_nothing_behind():
    script = _script()
    block = _handover_block()
    # exec skips the EXIT trap, so the second stage inherits the cleanup.
    assert 'BPANEL_UPDATE_PREVIOUS_COPY="${BPANEL_UPDATE_STABLE_COPY:-}"' in block
    assert 'RELEASE_WORK_DIR="${RELEASE_WORK_DIR:-}"' in block
    assert (
        'rm -f "${BPANEL_UPDATE_STABLE_COPY:-}" "${BPANEL_UPDATE_PREVIOUS_COPY:-}"' in script
    )
    # ...and the work dir it was handed must not be wiped out on the way in.
    assert 'RELEASE_WORK_DIR=""' not in script


def test_the_second_stage_does_not_snapshot_the_database_twice():
    script = _script()
    assert '''if [[ -n "${BPANEL_UPDATE_STAGE2:-}" ]]; then
  log "Continuing with the updater shipped in this release"
else
  log "Backing up SQLite DB before update"
  backup_db''' in script
