#!/usr/bin/env bash
# Buat backup SQLite di luar proses aplikasi. Aman dijalankan saat server hidup.
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "Virtualenv belum siap. Jalankan run.sh terlebih dahulu." >&2
  exit 1
fi

exec .venv/bin/python backup.py
