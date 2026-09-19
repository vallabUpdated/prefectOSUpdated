#!/usr/bin/env bash
# PrefectOS deploy: pull -> build UI -> restart -> health-check -> auto-rollback.
# Usage on the VM:   bash scripts/deploy.sh            (deploy latest main)
#                    bash scripts/deploy.sh v8.1       (deploy a tag)
set -uo pipefail
REPO_DIR="${REPO_DIR:-$HOME/prefectOSUpdated/current}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/ingest/metrics}"
SERVICE="${SERVICE:-prefectos}"
UI_SERVICE="${UI_SERVICE:-prefectos-ui}"
TARGET="${1:-main}"

cd "$REPO_DIR" || { echo "✗ REPO_DIR not found: $REPO_DIR"; exit 1; }
PREV=$(git rev-parse --short HEAD)
echo "== current: $PREV  ->  deploying: $TARGET"
git fetch --all --tags --quiet
git checkout --quiet "$TARGET" && git pull --quiet 2>/dev/null || true
NEW=$(git rev-parse --short HEAD)

build_ui() {
  [ -d "$REPO_DIR/ui" ] && command -v npm >/dev/null 2>&1 || return 0
  echo "[deploy] building UI…"
  ( cd "$REPO_DIR/ui" && { npm ci --silent 2>/dev/null || npm install --silent; } && npm run build )
}

# Build BEFORE any restart: a failed build aborts the deploy and the old
# bundle keeps serving — never ship a backend/UI mismatch.
if ! build_ui; then
  echo "✗ UI build FAILED — aborting deploy, reverting checkout to $PREV"
  git checkout --quiet "$PREV"
  exit 1
fi

sudo systemctl restart "$SERVICE"
systemctl list-unit-files 2>/dev/null | grep -q "^$UI_SERVICE" && sudo systemctl restart "$UI_SERVICE"
systemctl list-unit-files 2>/dev/null | grep -q "^prefectos-email" && sudo systemctl restart prefectos-email

echo "== restarted, health-checking $HEALTH_URL"
for i in 1 2 3 4 5 6; do
  sleep 3
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "✔ healthy on $NEW — deploy complete (backend + UI)"
    exit 0
  fi
done

echo "✗ health check FAILED — rolling back to $PREV"
git checkout --quiet "$PREV"
build_ui || true
sudo systemctl restart "$SERVICE"
systemctl list-unit-files 2>/dev/null | grep -q "^$UI_SERVICE" && sudo systemctl restart "$UI_SERVICE"
sleep 3
curl -fsS "$HEALTH_URL" >/dev/null 2>&1 \
  && echo "✔ rollback healthy on $PREV" \
  || echo "✗ rollback ALSO unhealthy — check: journalctl -u $SERVICE -n 50"
exit 1
