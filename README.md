# AeroAssess — Portal Asesmen & Uji Kompetensi

Repositori siap *clone* dan *deploy* di **Ubuntu Server (22.04 / 24.04 LTS)**, termasuk integrasi **aaPanel (Nginx Reverse Proxy)**.

---

## 1. Deploy Cepat di Ubuntu + aaPanel (1 Perintah)

```bash
git clone <URL_REPO_ANDA> /opt/aeroassess
cd /opt/aeroassess
chmod +x deploy.sh
./deploy.sh
```

> Gunakan `./deploy.sh --ssl` jika domain di aaPanel sudah memakai HTTPS (SSL).
> Gunakan `./deploy.sh --port 8001` jika port `8000` sudah terpakai aplikasi lain.

Skrip `deploy.sh` otomatis:
1. Menginstal dependensi Ubuntu (`python3-venv`, `libreoffice-writer`, `bubblewrap`, `openssl`).
2. Menyiapkan virtualenv `app/.venv` dan menginstal `app/requirements.txt`.
3. Membuat `app/.env` dengan `HOST=127.0.0.1` dan `TRUST_PROXY=1`.
4. Memasang dan menjalankan `systemd` service `aeroassess` serta memverifikasi `/api/health`.

---

## 2. Konfigurasi Website di aaPanel

> **Penting:** Jangan arahkan *Document Root* aaPanel ke `app/static/` sebagai static site biasa, karena request `/api/*` akan mengembalikan `404 Not Found`.

Di panel **aaPanel**:
1. Buka **Website → Add site** (atau pilih domain yang sudah ada, misal `ases.daemonode.com`).
2. Buka **Settings → Reverse proxy → Add reverse proxy**:
   - **Proxy name**: `aeroassess`
   - **Target URL**: `http://127.0.0.1:8000`
   - **Sent domain**: `$host`
3. Buka **Settings → Config** (Nginx) dan pastikan tidak ada blok static/PHP (`location ~ .*\.(js|css)$` atau `root`) yang mengintersep request sebelum `location /`. Contoh bersih ada di `deploy/aapanel-nginx.conf`.
4. Jika sudah mengaktifkan SSL (HTTPS) di aaPanel, pastikan di `app/.env` bernilai:
   ```env
   COOKIE_SECURE=1
   TRUST_PROXY=1
   HSTS=1
   ```
   Lalu restart service:
   ```bash
   sudo systemctl restart aeroassess
   ```

---

## 3. Update Kode dari GitHub

```bash
cd /opt/aeroassess
git pull
sudo systemctl restart aeroassess
```

---

## 4. Menjalankan Manual (Tanpa Systemd)

```bash
./install.sh
cd app && ./run.sh
```

---

## 5. Tes

```bash
cd app
.venv/bin/pytest -q
```
