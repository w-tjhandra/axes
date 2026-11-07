#!/usr/bin/env bash
# Jalankan aplikasi UKK. Semua konfigurasi lewat environment variable.
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Virtualenv belum siap. Jalankan:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

exec .venv/bin/uvicorn main:app --host "$HOST" --port "$PORT"
