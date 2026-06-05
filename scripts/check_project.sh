#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Sync frontend fallback entry"
cp deploy/frontend/index.html deploy/frontend/app.html

echo "==> Python syntax check"
python3 -m py_compile deploy/backend/main.py

echo "==> Frontend inline script syntax check"
python3 - <<'PY'
from pathlib import Path

text = Path('deploy/frontend/index.html').read_text()
start = text.index('<script>') + len('<script>')
end = text.rindex('</script>')
Path('/tmp/zhiku-inline.js').write_text(text[start:end])
PY

node --check /tmp/zhiku-inline.js
rm -f /tmp/zhiku-inline.js

echo "==> Sensitive and temporary file guard"
if git ls-files --error-unmatch deploy/.env >/dev/null 2>&1; then
  echo "ERROR: deploy/.env is tracked by git; stop before sharing or deploying." >&2
  exit 1
fi

if git ls-files --error-unmatch handover/01-SECRETS-AND-ACCOUNTS.md >/dev/null 2>&1; then
  echo "ERROR: handover/01-SECRETS-AND-ACCOUNTS.md is tracked by git; stop before sharing." >&2
  exit 1
fi

echo "OK: project checks passed"
