#!/usr/bin/env bash
# PrefectOS deploy: pull -> restart -> health-check -> auto-rollback.
# Usage on the VM:   bash scripts/deploy.sh            (deploy latest main)
#                    bash scripts/deploy.sh v8.1       (deploy a tag)
set -uo pipefail
REPO_DIR="${REPO_DIR:-$HOME/prefectos/repo}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/ingest/metrics}"
SERVICE="${SERVICE:-prefectos}"
TARGET="${1:-main}"

cd "$REPO_DIR"
PREV=$(git rev-parse --short HEAD)
echo "== current: $PREV  ->  deploying: $TARGET"
git fetch --all --tags --quiet
git checkout --quiet "$TARGET" && git pull --quiet 2>/dev/null || true
NEW=$(git rev-parse --short HEAD)

sudo systemctl restart "$SERVICE"
echo "== restarted, health-checking $HEALTH_URL"
for i in 1 2 3 4 5 6; do
  sleep 3
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "✔ healthy on $NEW — deploy complete"
    exit 0
  fi
done

echo "✗ health check FAILED — rolling back to $PREV"
git checkout --quiet "$PREV"
sudo systemctl restart "$SERVICE"
sleep 3
curl -fsS "$HEALTH_URL" >/dev/null 2>&1 \
  && echo "✔ rollback healthy on $PREV" \
  || echo "✗ rollback ALSO unhealthy — check: journalctl -u $SERVICE -n 50"
exit 1
