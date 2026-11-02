#!/usr/bin/env bash
# FraudShield – one-step local setup for macOS / Linux.
#   bash setup.sh
# Safe to run again: it never overwrites an existing backend/.env and never deletes data.
# Needs Python 3.11+, Node 18+ and a running MySQL 8 server.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

step() { printf '\n==> %s\n' "$1"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "$1 was not found. $2" >&2; exit 1; }; }
secret() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }

need python3 'Install Python 3.11+.'
need npm 'Install Node.js 18+.'

step 'Backend: virtual environment and dependencies'
PY="$BACKEND/.venv/bin/python"
[ -x "$PY" ] || python3 -m venv "$BACKEND/.venv"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$BACKEND/requirements.txt"

step 'Backend: configuration (backend/.env)'
if [ -f "$BACKEND/.env" ]; then
  echo 'backend/.env already exists - left unchanged.'
else
  read -r -p 'MySQL host [localhost]: ' DB_HOST; DB_HOST=${DB_HOST:-localhost}
  read -r -p 'MySQL port [3306]: ' DB_PORT; DB_PORT=${DB_PORT:-3306}
  read -r -p 'MySQL user [root]: ' DB_USER; DB_USER=${DB_USER:-root}
  read -r -s -p 'MySQL password: ' DB_PASS; echo
  read -r -p 'Database name [bank]: ' DB_NAME; DB_NAME=${DB_NAME:-bank}
  DB_PASS_ENC=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$DB_PASS")
  python3 - "$BACKEND/.env.example" "$BACKEND/.env" \
    "mysql+pymysql://$DB_USER:$DB_PASS_ENC@$DB_HOST:$DB_PORT/$DB_NAME?charset=utf8mb4" "$(secret)" "$(secret)" <<'PYEOF'
import re, sys
src, dst, url, key, jwt_key = sys.argv[1:]
text = open(src, encoding='utf-8').read()
for name, value in (('DATABASE_URL', url), ('SECRET_KEY', key), ('JWT_SECRET_KEY', jwt_key),
                    ('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173')):
    text = re.sub(rf'(?m)^{name}=.*$', lambda _: f'{name}={value}', text)
open(dst, 'w', encoding='utf-8').write(text)
PYEOF
  chmod 600 "$BACKEND/.env"
  echo 'Created backend/.env (random secret keys; dummy logins from .env.example).'
fi

step 'Database: create it if missing, then run every migration and seeder'
(cd "$BACKEND" && "$PY" -m flask --app app.py init-db)

step 'Frontend: dependencies'
(cd "$FRONTEND" && npm ci --no-audit --no-fund)

step 'Done'
cat <<EOF
Start the app in two terminals:
  backend : cd backend && .venv/bin/python app.py     (http://127.0.0.1:5000)
  frontend: cd frontend && npm run dev                (http://localhost:3000)
Run the tests: cd backend && .venv/bin/python -m pytest -q
Dummy logins are listed in README.md (section 2) and set in backend/.env.
EOF
