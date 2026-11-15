#!/usr/bin/env bash
# ==============================================================================
# One-Command Deploy Script untuk AeroAssess di Ubuntu Server + aaPanel
# Penggunaan:
#   ./deploy.sh                  # Deploy dengan port default 8000 (HTTP/Reverse Proxy)
#   ./deploy.sh --port 8000      # Tentukan port lokal uvicorn
#   ./deploy.sh --ssl            # Aktifkan COOKIE_SECURE=1 & HSTS=1 (wajib untuk HTTPS)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/app"
SERVICE_NAME="aeroassess"
PORT="8000"
USE_SSL="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:?Port harus diisi}"
      shift 2
      ;;
    --ssl)
      USE_SSL="1"
      shift
      ;;
    -h|--help)
      echo "Penggunaan: $0 [--port 8000] [--ssl]"
      exit 0
      ;;
    *)
      echo "Argumen tidak dikenal: $1" >&2
      exit 1
      ;;
  esac
done

RUN_USER="${SUDO_USER:-$(whoami)}"
SUDO=""
if [[ $EUID -ne 0 ]]; then
  SUDO="sudo"
fi

echo "=== [1/6] Instalasi dependensi sistem Ubuntu ==="
if command -v apt-get >/dev/null 2>&1; then
  ${SUDO} apt-get update -y
  ${SUDO} apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    libreoffice-writer \
    bubblewrap \
    openssl \
    curl \
    git
fi

echo "=== [2/6] Menyiapkan Python virtualenv & dependensi ==="
cd "${APP_DIR}"
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "=== [3/6] Menyiapkan .env produksi ==="
if [[ ! -f ".env" ]]; then
  cat > .env <<EOF
HOST=127.0.0.1
PORT=${PORT}
TRUST_PROXY=1
COOKIE_SECURE=${USE_SSL}
HSTS=${USE_SSL}
DB_PATH=./data/ukk.db
BACKUP_DIR=./backups
EOF
  echo "[*] File app/.env dibuat (PORT=${PORT}, COOKIE_SECURE=${USE_SSL})."
else
  echo "[*] File app/.env sudah ada, tidak ditimpa."
fi

mkdir -p data backups
chmod 700 data backups

echo "=== [4/6] Memasang systemd service (${SERVICE_NAME}) ==="
TMP_SERVICE="$(mktemp)"
cat > "${TMP_SERVICE}" <<EOF
[Unit]
Description=AeroAssess Assessor & Competency Portal
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn main:app --host 127.0.0.1 --port ${PORT}
Restart=always
RestartSec=3
KillMode=process
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

${SUDO} mv "${TMP_SERVICE}" "/etc/systemd/system/${SERVICE_NAME}.service"
${SUDO} chmod 644 "/etc/systemd/system/${SERVICE_NAME}.service"
${SUDO} systemctl daemon-reload
${SUDO} systemctl enable --now "${SERVICE_NAME}"
${SUDO} systemctl restart "${SERVICE_NAME}"

echo "=== [5/6] Verifikasi healthcheck lokal ==="
sleep 2
if curl -fsS "http://127.0.0.1:${PORT}/api/health"; then
  echo ""
  echo "[OK] Backend AeroAssess berjalan di http://127.0.0.1:${PORT}"
else
  echo ""
  echo "[!] Backend belum merespons. Cek log dengan: sudo journalctl -u ${SERVICE_NAME} -n 50" >&2
  exit 1
fi

echo ""
echo "=== [6/6] Langkah Setup di aaPanel (WAJIB agar /api/* tidak 404) ==="
echo "1. Buka aaPanel -> Website -> Add site (atau pilih domain Anda)."
echo "2. Masuk ke Settings domain -> Reverse proxy -> Add reverse proxy:"
echo "   - Proxy name : aeroassess"
echo "   - Target URL : http://127.0.0.1:${PORT}"
echo "   - Sent domain: \$host"
echo "3. Pastikan di Config Nginx domain tidak ada rule static/PHP yang menimpa 'location /'."
echo "   Contoh lengkap tersedia di: ${SCRIPT_DIR}/deploy/aapanel-nginx.conf"
echo "4. Jika memakai HTTPS (SSL Let's Encrypt di aaPanel), aktifkan COOKIE_SECURE=1 & HSTS=1"
echo "   di ${APP_DIR}/.env lalu jalankan: sudo systemctl restart ${SERVICE_NAME}"
