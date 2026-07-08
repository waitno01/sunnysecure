#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
WEB="$ROOT/web"

cd "$ROOT"

if [[ ! -f config/config.json ]]; then
  echo "Missing config/config.json — copy from README and fill in your values."
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3.14 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [[ ! -d web/node_modules ]]; then
  (cd web && npm install)
fi

echo "[*] Building frontend..."
(cd web && npm run build)

echo "[*] Starting services with PM2..."
pm2 start ecosystem.config.cjs

echo
echo "[+] AutoSecure is running."
echo "    API:      http://127.0.0.1:8000"
echo "    Web UI:   http://127.0.0.1:3000"
echo "    Logs:     pm2 logs"
echo "    Status:   pm2 status"
echo
echo "Before the bot works, edit config/config.json with your Discord bot token and owner ID."
echo "For public access, configure cloudflared.yml and run: cloudflared tunnel --config cloudflared.yml run"
