#!/usr/bin/env bash
# repair-update.sh: bring a BPanel whose Update button fails back to the
# newest release, in one command.
#
#   curl -fsSL https://gitlab.sieunhim.com/bnix/bpanel/-/raw/main/installer/repair-update.sh | sudo bash
#
# Why it is needed: BPanel v1.7.2 moved the code to GitLab, but the update
# launcher of v1.7.2 - v1.8.1 (/usr/local/sbin/bpanel-update) could only find
# the updater on GitHub. On those servers the Update button fails with
# "Cannot tell where the updater of https://gitlab.sieunhim.com/bnix/bpanel.git
# is", and a fixed release cannot install itself through the broken launcher.
# This script runs the updater of the newest release from GitLab once; that
# update installs the fixed launcher, and the button works from then on.
#
# It changes nothing by itself: the update is the same one the panel runs.
# Log: /root/bpanel-repair-update.log
set -euo pipefail

REPO="https://gitlab.sieunhim.com/bnix/bpanel"
LOG=/root/bpanel-repair-update.log

say() { printf '==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "run as root (sudo bash)"
[[ -d /opt/bpanel ]] || fail "no BPanel here (/opt/bpanel is missing)"
command -v curl >/dev/null 2>&1 || fail "curl is not installed (apt-get install -y curl)"
command -v git >/dev/null 2>&1 || fail "git is not installed (apt-get install -y git)"

before="$(cat /opt/bpanel/VERSION 2>/dev/null || echo unknown)"
say "BPanel installed: ${before}"

if pgrep -af '^(/bin/bash|bash) .*installer/update\.sh' >/dev/null 2>&1; then
  fail "an update is already running; wait for it to finish, then try again"
fi

# The newest release, as the launcher picks it.
tag="$(git ls-remote --tags --refs "${REPO}.git" 'refs/tags/v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null \
  | awk '{ sub("refs/tags/", "", $2); print $2 }' | sort -V | tail -n 1)"
[[ -n "$tag" ]] || fail "could not read the releases from ${REPO} - check this server's network"
say "Newest release: ${tag}"

# The updater of that release, checked before it runs as root.
work="$(mktemp -d /tmp/bpanel-repair.XXXXXX)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/installer"
script="$work/installer/update.sh"
curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o "$script" "${REPO}/-/raw/${tag}/installer/update.sh" \
  || fail "could not download the updater of ${tag}"
if [[ "$(head -n 1 "$script")" != "#!/usr/bin/env bash" ]] || ! grep -q 'BPANEL_UPDATE_STABLE_COPY' "$script" || ! bash -n "$script"; then
  fail "the file downloaded for ${tag} is not BPanel's updater; nothing was run"
fi

say "Updating to ${tag} (log: ${LOG}); this takes a few minutes..."
set +e
# </dev/null: run as `curl | bash`, stdin is the rest of this script.
REPO_URL="${REPO}.git" UPDATE_CHANNEL=release \
  BPANEL_UPDATER_URL="${REPO}/-/raw/{ref}/installer/update.sh" \
  bash "$script" --release </dev/null 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}
set -e

after="$(cat /opt/bpanel/VERSION 2>/dev/null || echo unknown)"
echo
if [[ $status -eq 0 ]] && grep -q "Update completed" "$LOG"; then
  say "Done: BPanel ${before} -> ${after}. The Update button works again from now on."
  say "Hard-refresh the panel in the browser (Ctrl + Shift + R)."
else
  printf 'ERROR: the update did not finish (exit %s). Send the last lines of %s:\n\n' "$status" "$LOG" >&2
  tail -n 20 "$LOG" >&2
  exit 1
fi
