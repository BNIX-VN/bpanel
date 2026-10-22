#!/usr/bin/env bash
set -euo pipefail

# The panel's own GitLab since 2026-10-22. BPANEL_GITHUB is still read, for a
# script that set it.
BPANEL_SOURCE="${BPANEL_SOURCE:-${BPANEL_GITHUB:-https://gitlab.sieunhim.com/bnix/bpanel}}"
BPANEL_SOURCE="${BPANEL_SOURCE%.git}"
bpanel_latest_tag() {
  local url
  case "$BPANEL_SOURCE" in
    https://github.com/*) url="https://api.github.com/repos/${BPANEL_SOURCE#https://github.com/}/tags?per_page=100" ;;
    *) url="${BPANEL_SOURCE%/*/*}/api/v4/projects/$(printf '%s' "${BPANEL_SOURCE#https://*/}" | sed 's|/|%2F|g')/repository/tags?per_page=100" ;;
  esac
  # GitLab answers on one line, GitHub one field a line: split on commas
  # so both read the same.
  curl -fsSL --connect-timeout 10 --max-time 60 "$url" \
    | tr ',' '\n' \
    | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\(v[^"]*\)".*/\1/p' \
    | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
    | sort -V \
    | tail -n 1
}
bpanel_tarball_url() {
  case "$BPANEL_SOURCE" in
    https://github.com/*) printf '%s/archive/refs/tags/%s.tar.gz\n' "$BPANEL_SOURCE" "$1" ;;
    *) printf '%s/-/archive/%s/%s-%s.tar.gz\n' "$BPANEL_SOURCE" "$1" "${BPANEL_SOURCE##*/}" "$1" ;;
  esac
}
INSTALLER_REL_PATH="${INSTALLER_REL_PATH:-installer/install.sh}"

latest_tag="$(
  if [[ -n "${BPANEL_VERSION:-}" ]]; then
    printf '%s\n' "${BPANEL_VERSION}"
  else
    bpanel_latest_tag
  fi
)"

if [[ -z "$latest_tag" ]]; then
  echo "ERROR: Could not detect latest BPanel release tag." >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'cd /; rm -rf "$tmp_dir"' EXIT

echo "==> Installing ${latest_tag}"
curl -fsSL "$(bpanel_tarball_url "$latest_tag")" -o "$tmp_dir/source.tar.gz"
tar -xzf "$tmp_dir/source.tar.gz" -C "$tmp_dir"
source_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d -name 'bpanel-*' | head -n 1)"
[[ -n "$source_dir" && -d "$source_dir" ]] || {
  echo "ERROR: Could not extract BPanel source archive." >&2
  exit 1
}
cd "$source_dir"
chmod +x "$INSTALLER_REL_PATH" installer/update.sh installer/rescue-firewall.sh
bash "$INSTALLER_REL_PATH"
