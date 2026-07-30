#!/usr/bin/env bash
set -euo pipefail

BPANEL_GITHUB="${BPANEL_GITHUB:-https://github.com/BNIX-VN/bpanel}"
BPANEL_REPO_SLUG="${BPANEL_GITHUB#*github.com/}"
INSTALLER_REL_PATH="${INSTALLER_REL_PATH:-installer/install.sh}"

latest_tag="$(
  if [[ -n "${BPANEL_VERSION:-}" ]]; then
    printf '%s\n' "${BPANEL_VERSION}"
  else
    curl -fsSL "https://api.github.com/repos/${BPANEL_REPO_SLUG}/tags?per_page=100" \
      | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\(v[^"]*\)".*/\1/p' \
      | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' \
      | sort -V \
      | tail -n 1
  fi
)"

if [[ -z "$latest_tag" ]]; then
  echo "ERROR: Could not detect latest BPanel release tag." >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'cd /; rm -rf "$tmp_dir"' EXIT

echo "==> Installing ${latest_tag}"
curl -fsSL "${BPANEL_GITHUB}/archive/refs/tags/${latest_tag}.tar.gz" -o "$tmp_dir/source.tar.gz"
tar -xzf "$tmp_dir/source.tar.gz" -C "$tmp_dir"
source_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d -name 'bpanel-*' | head -n 1)"
[[ -n "$source_dir" && -d "$source_dir" ]] || {
  echo "ERROR: Could not extract BPanel source archive." >&2
  exit 1
}
cd "$source_dir"
chmod +x "$INSTALLER_REL_PATH" installer/update.sh installer/rescue-ufw-blocklist.sh
bash "$INSTALLER_REL_PATH"
