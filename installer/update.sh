#!/usr/bin/env bash
# Update BPanel on a running VPS without reinstalling the full stack.
# Run on the server as root after uploading the new source.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root"
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/bpanel}"
BACKEND_DIR="${APP_DIR}/backend"
FRONTEND_DIR="${APP_DIR}/frontend"
NGINX_CONF="/etc/nginx/sites-available/bpanel.conf"

log() { echo ""; echo "==> $1"; }

[[ -d "$BACKEND_DIR" ]]  || { echo "Missing $BACKEND_DIR";  exit 1; }
[[ -d "$FRONTEND_DIR" ]] || { echo "Missing $FRONTEND_DIR"; exit 1; }

log "Updating backend dependencies"
cd "$BACKEND_DIR"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

log "Building frontend (clean rebuild)"
cd "$FRONTEND_DIR"
# Always nuke Vite cache and dist to guarantee a fresh hash on each deploy.
rm -rf dist .vite node_modules/.vite
if [[ ! -d node_modules || package.json -nt node_modules ]]; then
  rm -rf node_modules package-lock.json
  npm install
fi
VITE_API_URL=/api npm run build

if [[ ! -f dist/index.html ]]; then
  echo "Frontend build failed: dist/index.html not found"
  exit 1
fi
HASHED=$(grep -oE 'index-[a-zA-Z0-9_-]+\.js' dist/index.html | head -n1 || true)
echo "Built bundle: ${HASHED:-unknown}"

log "Restarting bpanel-api"
systemctl restart bpanel-api

log "Reloading nginx"
nginx -t
systemctl reload nginx

log "Health check"
for _ in {1..15}; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "API is healthy."
    echo "Update completed."
    echo ""
    echo "If the browser still shows the old UI, do a hard refresh (Ctrl+Shift+R)."
    echo "If you previously installed BPanel, the nginx config may still cache index.html."
    echo "To install the latest nginx config, re-run installer/install.sh once."
    exit 0
  fi
  sleep 1
done

echo "API did not respond. Check logs:"
echo "  journalctl -u bpanel-api -n 100 --no-pager"
exit 1
