#!/usr/bin/env bash
#
# Deploy the latest committed version on the VPS.
#   Run as:  sudo /home/exams/app/deploy.sh
#
# Pulls from GitHub into /home/exams/app (the backend runs straight from here),
# copies the three frontend source files into nginx's web root, fixes ownership
# and permissions, restarts the service, and verifies it came back up.
#
# The vendored browser libraries (frontend/vendor/) are git-ignored and change
# only when a library version is bumped; re-fetch them manually in that rare case
# with frontend/fetch-vendor.sh and copy them to /home/exams/frontend/vendor/.

set -euo pipefail

APP=/home/exams/app
FRONTEND=/home/exams/frontend

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo: sudo $APP/deploy.sh" >&2
  exit 1
fi

echo "==> Pulling latest from GitHub"
sudo -u exams git -C "$APP" pull --ff-only origin main

echo "==> Syncing frontend to nginx web root"
install -o exams -g exams -m 644 "$APP/frontend/index.html" "$FRONTEND/index.html"
install -o exams -g exams -m 644 "$APP/frontend/style.css"  "$FRONTEND/style.css"
install -o exams -g exams -m 644 "$APP/frontend/app.js"     "$FRONTEND/app.js"

echo "==> Restarting service"
systemctl restart exams.service
sleep 1

if curl -sf http://127.0.0.1:8003/api/health >/dev/null; then
  echo "==> Done — service is healthy."
else
  echo "WARNING: health check failed. Inspect with:" >&2
  echo "         sudo journalctl -u exams.service -n 30 --no-pager" >&2
  exit 1
fi
