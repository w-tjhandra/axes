#!/usr/bin/env bash
# ==============================================================================
# Setup & Installation Script untuk AeroAssess di Ubuntu VPS (22.04 / 24.04 LTS)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app"

echo "=== [1/5] Memeriksa & Menginstal Paket Dependensi Sistem Ubuntu ==="
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y \
        python3 \
        python3-venv \
        python3-pip \
        libreoffice \
        libreoffice-writer \
        bubblewrap \
        openssl \
        curl \
        git
else
    echo "[!] Peringatan: apt-get tidak ditemukan. Pastikan Python 3.11+, LibreOffice, & bubblewrap terpasang."
fi

echo "=== [2/5] Menyiapkan Virtual Environment Python ==="
cd "${APP_DIR}"

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
fi

echo "=== [3/5] Menginstal Dependensi Python (requirements.txt) ==="
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "=== [4/5] Menyiapkan File Konfigurasi Lingkungan (.env) ==="
if [[ ! -f ".env" ]]; then
    cp .env.example .env
    echo "[*] File .env berhasil dibuat dari .env.example. Silakan edit sesuai kebutuhan produksi."
fi

# Pastikan folder penyimpanan runtime berizin tepat
mkdir -p data backups
chmod 700 data backups 2>/dev/null || true

echo "=== [5/5] Instalasi Selesai! ==="
echo ""
echo "AeroAssess siap dijalankan:"
echo "  1. Masuk ke direktori app: cd app"
echo "  2. Jalankan aplikasi:      ./run.sh"
echo "  3. Akses via browser di:   http://<IP-VPS-ANDA>:8000"
echo ""
echo "Untuk deployment background permanen (Systemd / Caddy / Nginx),"
echo "lihat petunjuk lengkap di README.md atau deploy/aeroassess.service."
