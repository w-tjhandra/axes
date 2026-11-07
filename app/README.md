# UKK Junior Network Technician — Aplikasi Penilaian

Aplikasi web satu layanan untuk menilai UKK skema **Junior Network Technician**.
Backend FastAPI + SQLite (WAL), frontend HTML/CSS/ES module tanpa build tool,
dan ekspor CSV/XLSX. Data instrumen: **13 unit**, **61 indikator**, **5 sub
kompetensi**.

## 1. Menjalankan

Prasyarat: Python 3.11+ (diuji dengan Python 3.14), `openssl` opsional untuk
backup terenkripsi.

```bash
cd app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # opsional, sesuaikan
./run.sh
```

Buka `http://127.0.0.1:8000/`. `run.sh` memuat `.env` bila ada, lalu menjalankan
`uvicorn` di `0.0.0.0:${PORT:-8000}`. Untuk produksi di belakang reverse proxy,
disarankan `HOST=127.0.0.1`.

Database default `app/data/ukk.db` dibuat dan di-seed otomatis saat pertama
kali jalan. **Menghapus file itu menghapus seluruh data penilaian.** Untuk
reset total:

```bash
rm -f data/ukk.db data/ukk.db-wal data/ukk.db-shm
./run.sh
```

## 2. Akun pertama dan TOTP

1. Saat database kosong, halaman menampilkan **Setup awal**.
2. Isi username (min. 3 karakter) dan password (min. 8 karakter).
3. Aplikasi menampilkan **secret TOTP** dan **URI `otpauth://`**. Tidak ada QR;
   masukkan secret/URI ke aplikasi authenticator (Google Authenticator,
   Aegis, 1Password, dan sejenisnya).
4. Masuk dengan username, password, dan kode 6 digit.

Hanya ada satu akun asesor. Setup kedua ditolak. Login dibatasi 5 percobaan per
60 detik per IP. Jika secret TOTP hilang, pulihkan dari backup atau buat
database baru (data lama hilang).

## 3. Alur penilaian

1. **Sekolah** — tambah sekolah, lalu tambah peserta manual atau impor CSV.
2. **Peserta** — nomor peserta unik per sekolah; nomor dipakai pada label
   pernyataan, misalnya `Ahmad (03)`.
3. **Penilaian** — mulai assessment, beri skor tiap indikator `0–3`, isi catatan
   bila perlu. Skor tersimpan otomatis dan idempoten.
4. **Kunci** — assessment terkunci setelah semua indikator terisi. Bila masih
   ada yang kosong, aplikasi meminta konfirmasi `confirm_empty`; indikator kosong
   dihitung 0 dan ditandai.
5. **Buka kunci** — hanya dengan alasan minimal 10 karakter; tercatat di audit.
6. **Hasil & ekspor** — lihat rekap per peserta, unduh CSV atau XLSX.

Impor CSV menerima pemisah `;` atau `,` dengan kolom `nomor`, `nama`, `kelas`.
Baris valid tetap masuk; baris duplikat/error dilaporkan tanpa membatalkan
seluruh impor.

Ekspor XLSX berisi tiga sheet: `Ringkasan`, `Detail Unit`, `Sub Kompetensi`.

## 4. Aturan perhitungan

- Skor indikator `0–3`; nilai unit = `total skor / (3 × jumlah indikator) × 100`.
- Unit lulus bila nilainya **≥ 70%** (dihitung integer, tanpa pembulatan perantara).
- Semua 13 unit lulus → `kompeten_penuh`.
- Bila tidak semua unit lulus, tetapi seluruh unit pada satu sub kompetensi lulus
  → `kompeten_sub` (sub dengan rata-rata tertinggi; seri dipilih urutan terkecil).
- Bila hanya sebagian unit lulus → `kompeten_unit`.
- Tidak ada unit lulus → `belum_kompeten`.
- Predikat dihitung dari rata-rata persen unit yang lulus: **≥ 90 Sangat Mahir**,
  **≥ 80 Mahir**, **≥ 70 Cakap**, selain itu `Tidak Memenuhi`. Predikat juga
  ditampilkan untuk `kompeten_unit`.
- Ambang dan template pernyataan dapat diubah di halaman **Config**; perubahan
  menaikkan versi instrumen. Assessment lama memakai snapshot instrumen saat
  dibuat, jadi hasil terkunci tidak berubah.

## 5. Instrumen dan catatan verifikasi

| No | Kode unit | Judul | Indikator |
|---:|---|---|---:|
| 1 | `J.611000.003.02` | Merancang Topologi Jaringan | 2 |
| 2 | `J.611000.004.01` | Merancang Pengalamatan Jaringan | 2 |
| 3 | `J.611000.008.02` | Menyiapkan Kabel Jaringan | 2 |
| 4 | `J.611000.009.02` | Memasang Kabel Jaringan | 3 |
| 5 | `J.611000.010.02` | Memasang Jaringan Nirkabel | 4 |
| 6 | `J.611000.011.02` | Memasang Perangkat Jaringan ke dalam Sistem Jaringan | 13 |
| 7 | `J.611000.012.02` | Mengkonfigurasi Switch pada Jaringan | 4 |
| 8 | `J.611000.006.01` | Merancang Keamanan Jaringan | 11 |
| 9 | `J.611000.015.02` | Memonitor Keamanan dan Pengaturan Akun Pengguna dalam Jaringan Komputer | 3 |
| 10 | `J.611000.020.01` | Mengoptimalkan Kinerja Sistem Jaringan | 9 |
| 11 | `J.611000.017.01` | Mengidentifikasi Sumber Kerusakan | 2 |
| 12 | `J.611000.018.02` | Memperbaiki Kerusakan Konfigurasi Jaringan | 2 |
| 13 | `J.611000.022.01` | Melakukan Backup dan Restore Konfigurasi Perangkat Jaringan | 4 |

Sub kompetensi:

- **SK-01** — 003, 004
- **SK-02** — 008, 009, 010, 011
- **SK-03** — 004, 011, 012
- **SK-04** — 006, 015, 020
- **SK-05** — 017, 018, 022

Dua indikator ditandai **usulan** (`is_proposed=1`) karena teks eksplisitnya
tidak ada di sumber instrumen, dan wajib diverifikasi asesor sebelum dipakai
resmi:

- `IND-026` (unit 011): konfigurasi router diuji ulang sebelum penilaian lanjut.
- `IND-061` (unit 022): restore dari file backup berhasil dan perangkat berfungsi.

Kode unit mengikuti pola SKKNI, tetapi **perlu diverifikasi** terhadap dokumen
SKKNI resmi (Q-102). Halaman **Config** menampilkan daftar indikator usulan.

## 6. Offline dan sinkronisasi

Frontend menyimpan perubahan skor yang gagal terkirim di IndexedDB (fallback
memori), menampilkan status offline, dan mencoba mengirim ulang otomatis tiap
15 detik serta saat koneksi kembali. Indikator yang tertunda ditandai di UI.
Tombol sync di header memaksa pengiriman ulang.

Google Sheets bersifat **opsional dan disabled-safe**. Bila env belum lengkap,
statusnya `disabled` dan aplikasi tetap berjalan. Untuk mengaktifkan:

```bash
GOOGLE_SHEETS_ID=1AbCdEf...
GOOGLE_SERVICE_ACCOUNT_JSON=/path/ke/service-account.json
```

Aktifkan Google Sheets API, buat service account, lalu **bagikan spreadsheet
ke email service account** sebagai Editor. Sinkronisasi satu arah (SQLite →
Sheets); Sheets bukan sumber kebenaran.

`SYNC_API_KEY` opsional untuk klien yang mengirim skor lewat
`POST /api/sync/scores` dengan header `X-API-Key`.

## 7. Backup dan restore

Backup memakai SQLite backup API (aman saat server hidup), retensi 30 hari.

```bash
./backup.sh
# atau dari UI: halaman Sync & Backup
```

Lokasi default `app/backups/`; ubah dengan `BACKUP_DIR`. Bila `BACKUP_KEY`
diset, hasilnya `ukk_*.sqlite3.enc` (AES-256-CBC, butuh `openssl`).

Restore:

```bash
# 1. Hentikan server
# 2. Dekripsi bila perlu
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_KEY \
  -in backups/ukk_20261106_120000.sqlite3.enc -out /tmp/restore.db

# 3. Ganti database (file .db lama disimpan sebagai cadangan)
mv data/ukk.db data/ukk.db.sebelum-restore
cp /tmp/restore.db data/ukk.db
rm -f data/ukk.db-wal data/ukk.db-shm

# 4. Jalankan lagi
./run.sh
```

## 8. Konfigurasi environment

Lihat `.env.example`. Ringkasan:

| Variabel | Default | Keterangan |
|---|---|---|
| `DB_PATH` | `app/data/ukk.db` | Path SQLite |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind `run.sh` |
| `SESSION_DAYS` | `7` | Umur sesi cookie |
| `COOKIE_SECURE` | mati | Wajib `1` di HTTPS |
| `TRUST_PROXY` | mati | `1` di belakang Caddy/Nginx |
| `HSTS` | mati | `1` untuk kirim header HSTS |
| `BACKUP_DIR` | `./backups` | Direktori backup |
| `BACKUP_KEY` | kosong | Enkripsi backup |
| `GOOGLE_SHEETS_ID` | kosong | Spreadsheet tujuan |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | kosong | Kredensial Sheets |
| `SYNC_API_KEY` | kosong | API key sync skor |

## 9. Contoh Caddy (HTTPS)

```caddyfile
ukk.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
```

Jalankan aplikasi dengan `HOST=127.0.0.1 COOKIE_SECURE=1 TRUST_PROXY=1 HSTS=1
./run.sh`, lalu `caddy run`. Caddy menangani TLS; aplikasi tidak perlu
membuka port ke publik.

## 10. Tes

```bash
cd app
.venv/bin/pytest -q
```

Tes mencakup aturan perhitungan murni, seed 13 unit/61 indikator, autentikasi
TOTP/CSRF, CRUD sekolah/peserta, impor CSV, alur skor–kunci–buka kunci, ekspor
CSV/XLSX, versioning config/snapshot, sync disabled-safe, dan backup.

## 11. Struktur

```
app/
  main.py          API FastAPI, keamanan, ekspor, config
  rules.py         aturan hitung 5.4/5.5/5.6 (murni)
  seed_data.py     13 unit, 61 indikator, 5 sub kompetensi
  db.py            skema SQLite, WAL, snapshot, audit
  auth.py          argon2, TOTP, sesi cookie, rate limit
  sheets.py        sinkronisasi Google Sheets (opsional)
  backup.py        backup SQLite + enkripsi opsional
  static/          frontend tanpa build (app.js, app.css, sw.js)
  tests/           pytest
  run.sh           menjalankan server
  backup.sh        membuat backup
```
