# 03-build — UKK Junior Network Technician

**Status:** selesai untuk revisi seed + artefak jalan.
**Tanggal:** 6 November 2026
**Lokasi:** `workspace/ukk-junior-network-tech/app/`
**Database:** `app/data/ukk.db` sudah dihapus dan di-seed ulang.

## 1. Ringkasan

Instrumen diperbaiki agar persis tabel 5.2 garis besar: 13 unit, 61 indikator,
5 sub kompetensi. Kode unit, judul, urutan, dan pemetaan indikator diganti;
aturan perhitungan di `rules.py` tidak diubah. Aplikasi FastAPI + SQLite WAL
dapat dijalankan lewat `./run.sh`, dan frontend memakai aset statis tanpa build.

Perubahan utama:

- `J.611000.003.02` sekarang **Merancang Topologi Jaringan** (bukan VLSM).
- `J.611000.004.01` sekarang **Merancang Pengalamatan Jaringan** (VLSM).
- `J.611000.010.02` sekarang **Memasang Jaringan Nirkabel**.
- `J.611000.012.02` sekarang **Mengkonfigurasi Switch pada Jaringan**.
- Kode lain mengikuti daftar yang diminta, termasuk `.01` pada 004, 006, 017,
  020, dan 022.
- Dua indikator usulan tetap ditandai: `IND-026` (unit 011) dan `IND-061`
  (unit 022).

## 2. File yang diubah/dibuat

| File | Perubahan |
|---|---|
| `app/seed_data.py` | Ditulis ulang: 13 unit/61 indikator/5 sub kompetensi sesuai tabel 5.2 |
| `app/tests/test_rules.py` | Ditambah tes kunci seed; kode unit lama diperbarui |
| `app/static/sw.js` | Service worker app-shell/offline (sebelumnya dirujuk tetapi belum ada) |
| `app/run.sh` | Executable; memuat `.env`; uvicorn `0.0.0.0:${PORT:-8000}` |
| `app/backup.sh` | Executable; menjalankan `backup.py` |
| `app/requirements.txt` | Dependensi runtime + test |
| `app/.env.example` | Contoh konfigurasi tanpa rahasia |
| `app/README.md` | Cara jalan, TOTP, alur, aturan, backup, Sheets, Caddy |
| `app/data/ukk.db` | Dihapus lalu dibuat ulang dari seed baru |

Tidak diubah: `rules.py`, `main.py`, `db.py`, `auth.py`, `sheets.py`,
`backup.py` (kecuali tidak ada perubahan aturan hitung).

## 3. Cara menjalankan

```bash
cd /home/chandra/workspace/ukk-junior-network-tech/app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # opsional
./run.sh
```

Buka `http://127.0.0.1:8000/`. Database kosong akan menampilkan **Setup awal**;
buat akun asesor, simpan secret TOTP, lalu login dengan kode 6 digit.

Reset data:

```bash
rm -f data/ukk.db data/ukk.db-wal data/ukk.db-shm
./run.sh
```

## 4. Hasil tes

Perintah:

```bash
cd /home/chandra/workspace/ukk-junior-network-tech/app
.venv/bin/pytest -q
```

Hasil:

```text
21 passed, 1 warning in 2.80s
```

Warning hanya deprecation `httpx` dari Starlette TestClient, bukan kegagalan.

Tes baru mengunci:

- Urutan, kode, judul, dan jumlah indikator persis tabel 5.2.
- Total 61 indikator.
- Pemetaan SK-01 s.d. SK-05 persis yang diminta.
- Aturan 70%, predikat, pernyataan 5.6, dan alur assessment tetap lulus.

## 5. Verifikasi server

Server dijalankan sementara di port 8765 dengan `PORT=8765 ./run.sh`, lalu
dihentikan.

| Pemeriksaan | Hasil |
|---|---|
| `GET /` | `200` |
| `GET /api/health` | `200`, `{"status":"ok","units":13,"indicators":61}` |
| `GET /api/auth/status` | `200`, `{"needs_setup":true,"authenticated":false}` |
| `GET /sw.js` | `200` |
| `GET /app.js` | `200` |
| `GET /app.css` | `200` |
| `GET /robots.txt` | `200` |
| `node --check static/app.js` | lulus |
| `node --check static/sw.js` | lulus |

Verifikasi data yang akan dirender UI dilakukan lewat API dengan database
sementara: 13 unit, 61 indikator, 5 sub kompetensi, dua indikator usulan, dan
tidak ada kode/judul lama. Login page statis memuat `id="login-view"` dan teks
`Masuk`.

## 6. Yang belum teruji

- **Interaksi browser nyata** (klik, modal, IndexedDB, service worker) belum
  dijalankan dengan browser/Playwright. Yang diverifikasi baru syntax check,
  HTTP static, dan respons API. Ini perlu smoke test manual sebelum dipakai.
- **Sinkronisasi Google Sheets live** belum diuji karena kredensial tidak ada.
  Status `disabled` sudah diuji; jalur tulis ke spreadsheet belum.
- **Backup terenkripsi** belum diuji end-to-end dengan `BACKUP_KEY` dan
  `openssl`; jalur backup tanpa enkripsi diuji lewat pytest.
- **Restore** belum diuji di lingkungan nyata; prosedur ada di README.
- **Kode unit** mengikuti pola SKKNI yang diminta, tetapi belum dicocokkan
  dengan dokumen SKKNI resmi (Q-102).
- **Dua teks indikator usulan** (`IND-026`, `IND-061`) perlu diverifikasi asesor
  (Q-101).
- **Setup TOTP** belum diuji dengan aplikasi authenticator nyata; tes memakai
  PyOTP.

## 7. Risiko

- Assessment lama tidak bisa dipertahankan setelah `data/ukk.db` dihapus. Ini
  disengaja karena seed lama salah; jika ada data produksi, restore dari backup
  lama tidak kompatibel dengan kode unit baru.
- Perubahan kode unit membuat tautan/laporan lama yang menyebut kode lama tidak
  valid. Ekspor baru memakai snapshot masing-masing assessment.
- Service worker meng-cache app shell. Setelah deploy versi baru, naikkan
  `CACHE_NAME` di `sw.js` atau lakukan hard reload agar aset tidak tertahan.
- `run.sh` default bind `0.0.0.0`; untuk produksi gunakan `HOST=127.0.0.1` di
  belakang reverse proxy dan `COOKIE_SECURE=1`.
- `BACKUP_DIR` default relatif terhadap direktori kerja; `run.sh` sudah `cd` ke
  direktori app, jadi backup masuk `app/backups/`.

## 8. Rollback

- Kode: kembalikan `seed_data.py` dan tes ke commit sebelumnya.
- Data: hentikan server, ganti `data/ukk.db` dengan backup terakhir, hapus
  `data/ukk.db-wal` dan `data/ukk.db-shm`, lalu jalankan ulang.
- Jika backup terenkripsi, dekripsi dengan `openssl enc -d -aes-256-cbc -pbkdf2`.

## 9. Catatan serah-terima

Database saat ini bersih dan **belum punya akun**. Langkah pertama penguji:
buka halaman, isi Setup awal, simpan secret TOTP, lalu login. Setelah itu tambah
sekolah/peserta atau impor CSV, mulai assessment, isi 61 indikator, dan kunci
untuk melihat hasil.

## 10. Perbaikan pasca-QA

**Tanggal:** 6 November 2026  
**Trigger:** QA No-Go (2 Major + 1 Minor blokir) — lihat `../04-qa.md`

### 10.1 File yang diubah

| File | Perubahan |
|---|---|
| `app/db.py` | Tambah unique index `idx_school_nama_norm` pada `school(lower(replace(nama,'  ',' ')))` |
| `app/main.py` | POST/PATCH `/api/schools` cek duplikat nama setelah normalisasi (spasi ganda + lower); return 409 `nama_exists` |
| `app/static/app.css` | `.table-wrap` pakai `overflow-x:auto; max-width:100%; -webkit-overflow-scrolling:touch`; header `th:first-child` & `th:last-child` sticky left/right; tabel `min-width:600px` |
| `app/static/app.css` | Accordion unit pakai native `<details><summary>`; hapus `.chevron` & JS toggle; `summary::-webkit-details-marker {display:none}` |
| `app/static/app.js` | `unitHtml()` render `<details class="unit-card">` + `<summary class="unit-head">`; event `toggle` update `state.openUnits` |
| `app/static/app.js` | `updateSyncPill()` tampilkan class `failed` + teks `"X gagal, Y pending"` bila `state.failedKeys.size > 0` |
| `app/static/app.js` | `openUnlockModal()` tambah `<span id="unlock-len">0</span>/10` merah <10, hijau ≥10; update on `input`; disable tombol <10 |

### 10.2 Verifikasi pytest

```bash
cd /home/chandra/workspace/ukk-junior-network-tech/app
.venv/bin/pytest -q
```

```
21 passed, 1 warning in 2.03s
```

### 10.3 Verifikasi mobile (Playwright 390×844)

| Skenario | Hasil | Screenshot |
|---|---|---|
| Login → Dashboard | ✅ | `fix-01-login-page.png`, `fix-02-dashboard.png` |
| Sekolah tabel tidak overflow, aksi terlihat | ✅ | `fix-03-schools-table.png` |
| POST sekolah duplikat nama → 409 `nama_exists` | ✅ | API test |
| Assessment accordion buka/tutup via touch | ✅ | `fix-04-assessment-accordion.png` |
| Unlock modal counter merah <10, hijau ≥10 | ✅ | `fix-05-unlock-modal-counter.png` |
| Offline queue → flush → badge update | ✅ | Sync pill check |

Screenshot tersimpan di `/tmp/opencode/qa-shots/fix-*.png`

### 10.4 Ringkasan perbaikan per bug

| Bug | Status | Detail |
|---|---|---|
| BUG-001 Major (tabel overflow) | ✅ | Wrapper `.table-wrap` + sticky header kolom aksi |
| BUG-002 Major (accordion touch) | ✅ | Native `<details><summary>` works on touch/keyboard |
| BUG-003 Minor (sekolah duplikat) | ✅ | Unique index + API check normalisasi nama |
| BUG-004 Minor (badge sync) | ✅ | `updateSyncPill()` tampilkan state `failed` |
| BUG-005 Minor (unlock counter) | ✅ | Char counter `#unlock-len` merah/hijau + disable tombol |
