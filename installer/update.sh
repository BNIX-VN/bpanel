#!/usr/bin/env bash
# Update BPanel from GitHub.
#
# This script is meant to live in a checkout of the BPanel repo (e.g.
# /opt/bpanel-source). It pulls the latest commit from origin/main, syncs the
# source into /opt/bpanel, rebuilds the frontend, restarts the API, and reloads
# nginx.
#
# Usage:
#   sudo bash installer/update.sh
#   sudo bash installer/update.sh --branch dev
#   APP_DIR=/srv/bpanel sudo -E bash installer/update.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root"
  exit 1
fi

# --- Config ----------------------------------------------------------------
APP_DIR="${APP_DIR:-/opt/bpanel}"                 # Production deployment dir
SOURCE_DIR="${SOURCE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REPO_URL="${REPO_URL:-https://github.com/bnixvn/bpanel.git}"
BRANCH="${BRANCH:-main}"
SKIP_PULL="${SKIP_PULL:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    --skip-pull) SKIP_PULL="true"; shift ;;
    --app-dir) APP_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,30p' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

log()  { echo ""; echo "==> $1"; }
fail() { echo "ERROR: $1" >&2; exit 1; }

# --- Pull latest source ----------------------------------------------------
if [[ "$SKIP_PULL" != "true" ]]; then
  if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    log "Cloning $REPO_URL to $SOURCE_DIR"
    git clone "$REPO_URL" "$SOURCE_DIR"
  fi
  log "Pulling latest from origin/$BRANCH"
  cd "$SOURCE_DIR"
  git fetch --all --prune
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
  echo "HEAD: $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"
fi

# --- Validate ---------------------------------------------------------------
[[ -d "$SOURCE_DIR/backend"  ]] || fail "Missing $SOURCE_DIR/backend"
[[ -d "$SOURCE_DIR/frontend" ]] || fail "Missing $SOURCE_DIR/frontend"

# --- Sync code into APP_DIR -------------------------------------------------
log "Syncing source to $APP_DIR"
mkdir -p "$APP_DIR"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'bpanel.db' \
    "$SOURCE_DIR/backend/" "$APP_DIR/backend/"
  rsync -a --delete \
    --exclude 'node_modules/' \
    --exclude 'dist/' \
    --exclude '.vite/' \
    "$SOURCE_DIR/frontend/" "$APP_DIR/frontend/"
else
  cp -r "$SOURCE_DIR/backend/."  "$APP_DIR/backend/"
  cp -r "$SOURCE_DIR/frontend/." "$APP_DIR/frontend/"
fi

# --- Refresh helper + sudoers (idempotent) ---------------------------------
if [[ -f "$SOURCE_DIR/installer/files/bpanel-helper.sh" ]]; then
  log "Refreshing /usr/local/sbin/bpanel-helper and /etc/sudoers.d/bpanel"
  if id -u bpanel >/dev/null 2>&1; then
    install -m 0750 -o root -g bpanel "$SOURCE_DIR/installer/files/bpanel-helper.sh" /usr/local/sbin/bpanel-helper
    install -m 0440 -o root -g root  "$SOURCE_DIR/installer/files/bpanel-sudoers"   /etc/sudoers.d/bpanel
    visudo -c -f /etc/sudoers.d/bpanel >/dev/null
  else
    echo "  (bpanel user not found; skipping helper refresh — run install.sh first)"
  fi
fi

# --- Restore ownership so bpanel user can read/write the deploy ------------
if id -u bpanel >/dev/null 2>&1; then
  chown -R bpanel:bpanel "$APP_DIR/backend" "$APP_DIR/frontend" 2>/dev/null || true
fi

# --- Backend ---------------------------------------------------------------
log "Updating backend dependencies"
cd "$APP_DIR/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

log "Compiling backend modules"
python -m py_compile \
  app/main.py \
  app/api/auth.py \
  app/api/users.py \
  app/api/websites.py \
  app/api/databases.py \
  app/api/maintenance.py \
  app/api/firewall.py \
  app/api/services.py \
  app/services/firewall.py \
  app/services/nginx.py \
  app/services/mariadb.py \
  app/services/wordpress.py \
  app/services/file_manager.py \
  app/services/backup.py \
  app/services/cron.py \
  app/services/php.py \
  app/schemas/schemas.py
deactivate

log "Restarting bpanel-api"
systemctl restart bpanel-api

# --- Frontend --------------------------------------------------------------
log "Building frontend (clean rebuild)"
cd "$APP_DIR/frontend"
rm -rf dist .vite node_modules/.vite

if [[ ! -d node_modules ]] || [[ package.json -nt node_modules ]]; then
  rm -rf node_modules package-lock.json
  npm install
fi
VITE_API_URL=/api npm run build

[[ -f dist/index.html ]] || fail "Frontend build failed: dist/index.html missing"
HASHED=$(grep -oE 'index-[a-zA-Z0-9_-]+\.js' dist/index.html | head -n1 || true)
echo "Built bundle: ${HASHED:-unknown}"

# --- Reload Nginx ----------------------------------------------------------
log "Reloading nginx"
nginx -t
systemctl reload nginx

# --- Health check ----------------------------------------------------------
log "Health check"
for _ in {1..20}; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "API is healthy."
    echo ""
    echo "Update completed."
    echo "If the browser still shows the old UI, hard refresh (Ctrl + Shift + R)."
    exit 0
  fi
  sleep 1
done

echo "API did not respond. Check logs:"
echo "  journalctl -u bpanel-api -n 100 --no-pager"
exit 1
