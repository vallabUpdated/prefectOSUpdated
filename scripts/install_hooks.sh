#!/usr/bin/env bash
# One-time per clone: wires the secret scan into git.
cd "$(git rev-parse --show-toplevel)"
cp scripts/secret_scan.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit scripts/secret_scan.sh
echo "✔ pre-commit secret scan installed"
