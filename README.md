# ==============================================================================
# AeroAssess — Portal Asesmen & Uji Kompetensi
# Panduan Singkat Instalasi & Deployment VPS Ubuntu
# ==============================================================================

Repositori ini siap di-*clone* dan dijalankan di VPS Ubuntu (Ubuntu 22.04 LTS / 24.04 LTS).

---

## 🚀 Cara Cepat (Quick Install)

Jalankan perintah berikut di VPS Ubuntu Anda:

```bash
# 1. Clone repositori
git clone <URL_REPO_ANDA> /opt/aeroassess
cd /opt/aeroassess

# 2. Jalankan skrip instalasi otomatis
chmod +x install.sh
./install.sh

# 3. Jalankan aplikasi
cd app
./run.sh
```

Akses portal melalui browser: `http://<IP-VPS-ANDA>:8000`

---

## ⚙️ Konfigurasi Environment (`app/.env`)

Salin dari contoh konfigurasi jika belum ada:
```bash
cp app/.env.example app/.env
nano app/.env
```

Beberapa konfigurasi penting untuk produksi di VPS:
- `HOST`: `127.0.0.1` (jika menggunakan reverse proxy Caddy/Nginx) atau `0.0.0.0` (jika akses IP langsung).
- `PORT`: `8000`
- `COOKIE_SECURE`: set ke `1` jika menggunakan HTTPS domain.
- `TRUST_PROXY`: set ke `1` jika di belakang reverse proxy.
- `HSTS`: set ke `1` untuk mengaktifkan HTTP Strict Transport Security.

---

## 🛠️ Deployment Produksi Otomatis (Systemd Service)

Agar aplikasi berjalan otomatis di background dan hidup kembali saat VPS reboot:

```bash
# 1. Salin template systemd service
sudo cp deploy/aeroassess.service /etc/systemd/system/

# 2. Sesuaikan User dan Path direktori jika bukan /opt/aeroassess
sudo nano /etc/systemd/system/aeroassess.service

# 3. Muat ulang dan aktifkan service
sudo systemctl daemon-reload
sudo systemctl enable --now aeroassess

# 4. Periksa status
sudo systemctl status aeroassess
```

---

## 🔒 Konfigurasi HTTPS dengan Caddy (Rekomendasi)

Caddy menangani sertifikat SSL Let's Encrypt secara otomatis tanpa ribet:

```bash
# Instal Caddy di Ubuntu
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# Salin konfigurasi Caddyfile
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile # Ganti nama domain Anda
sudo systemctl reload caddy
```

---

## 🧪 Menjalankan Tes

```bash
cd app
.venv/bin/pytest -q
```
