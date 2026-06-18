#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_DIR="${BENCH_DIR:-$HOME/frappe-bench}"
SITE_NAME="${SITE_NAME:-lifeline.localhost}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if ! command -v bench >/dev/null 2>&1; then
  echo "Bench CLI is not installed."
  echo "Install the official Frappe v15 prerequisites and frappe-bench first."
  exit 1
fi

if [[ ! -d "$BENCH_DIR" ]]; then
  bench init --frappe-branch version-15 --python "$PYTHON_BIN" "$BENCH_DIR"
fi

cd "$BENCH_DIR"

if [[ ! -d apps/erpnext ]]; then
  bench get-app --branch version-15 erpnext
fi

if [[ ! -e apps/lifeline_tpa ]]; then
  bench get-app --soft-link "$APP_ROOT"
fi

if [[ ! -d "sites/$SITE_NAME" ]]; then
  bench new-site "$SITE_NAME"
  bench --site "$SITE_NAME" install-app erpnext
fi

if ! bench --site "$SITE_NAME" list-apps | grep -qx "lifeline_tpa"; then
  bench --site "$SITE_NAME" install-app lifeline_tpa
fi

bench set-config -g developer_mode 1
bench --site "$SITE_NAME" migrate
bench build --app lifeline_tpa

echo "Development site ready: http://$SITE_NAME:8000"
echo "Run: cd $BENCH_DIR && bench start"

