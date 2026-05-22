#!/usr/bin/env bash
set -euo pipefail
APP_ROOT=/opt/welopc-ai-signal-radar
WEB_ROOT=/var/www/welopc-ai-signal-radar
LATEST_JSON="$APP_ROOT/site/ai-signal-live/data/latest.json"
cd "$APP_ROOT"
set -a
if [ -f "$APP_ROOT/.env" ]; then
  . "$APP_ROOT/.env"
fi
set +a
export PYTHONPATH="$APP_ROOT/src"
export AIHOT_APP_ROOT="$APP_ROOT"
export AIHOT_RUNTIME_ROOT=/opt/welopc-ai-signal-radar-runtime
export AIHOT_WEB_ROOT="$WEB_ROOT"
export AIHOT_DB_PATH=/opt/welopc-ai-signal-radar-runtime/aihot_repro.sqlite3
export AIHOT_LATEST_JSON="$LATEST_JSON"
export DEEPSEEK_AUTO_ENRICH=0
export DEEPSEEK_TIMEOUT_SECONDS=45
"$APP_ROOT/.venv/bin/python" -m ecom_research.cli ai-news-schedule-run --force
/usr/bin/timeout 10m "$APP_ROOT/.venv/bin/python" -m ecom_research.aihot_service import-latest --latest-json "$LATEST_JSON"
/bin/mkdir -p "$WEB_ROOT/data"
/usr/bin/install -m 0644 "$LATEST_JSON" "$WEB_ROOT/data/latest.json"
/bin/chown -R apache:apache "$WEB_ROOT/data"
