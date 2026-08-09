#!/usr/bin/env bash
# Pre-commit secret scan for PrefectOS — blocks real credential patterns.
# Installs as a git hook via:  bash scripts/install_hooks.sh
# Deliberately ignores test fixtures (sk-ant-secret / sk-ant-SECRET).
set -uo pipefail
PATTERNS=(
  'sk-ant-api[0-9a-zA-Z]{2}-[A-Za-z0-9_-]{20,}'   # Anthropic live keys
  'AKIA[0-9A-Z]{16}'                               # AWS access key IDs
  'gsk_[A-Za-z0-9]{20,}'                           # Groq keys
  'ghp_[A-Za-z0-9]{36}'                            # GitHub tokens
  'AIza[0-9A-Za-z_-]{35}'                          # Google API keys
  'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY'             # private keys
)
FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)
[ -z "$FILES" ] && exit 0
FAIL=0
for pat in "${PATTERNS[@]}"; do
  HITS=$(echo "$FILES" | xargs -r grep -lnE "$pat" 2>/dev/null || true)
  if [ -n "$HITS" ]; then
    echo "SECRET PATTERN [$pat] found in:"; echo "$HITS" | sed 's/^/    /'
    FAIL=1
  fi
done
if [ "$FAIL" = 1 ]; then
  echo ""
  echo "Commit BLOCKED. Remove the secret, rotate it if it was real,"
  echo "and keep credentials in /etc/prefectos.env (never in the repo)."
  exit 1
fi
exit 0
