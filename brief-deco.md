# Brief untuk Deco — T-002 Bangun MVP Platform Penilaian UKK

## 1. Konteks
Bangun aplikasi web **siap jalan** untuk satu asesor menilai UKK Junior Network Technician.
Sumber aturan: `02-prd.md` v0.2. Namun **garis besar pengguna tetap menang** bila ada konflik.
Workspace: `/home/chandra/workspace/ukk-junior-network-tech/`
App: `/home/chandra/workspace/ukk-junior-network-tech/app/`
Venv sudah disiapkan di `app/.venv` (fastapi, uvicorn, openpyxl, pyotp, argon2-cffi, itsdangerous, httpx, google-auth, google-api-python-client).

## 2. Koreksi wajib atas PRD (ikuti ini, bukan bagian yang bertentangan)
1. **Kode unit = kode SKKNI asli**, bukan UNIT-01..13. Gunakan kode dari tabel 5.2 garis besar (mis. `J.611000.003.02`).
2. **Peserta memakai `nomor`** (nomor peserta/absen), bukan `nisn`. Kolom: nomor, nama, kelas.
3. **Auth = cookie sesi** (HttpOnly, SameSite=Strict, Secure via env), bukan bearer access/refresh token. API key statis hanya untuk endpoint sync internal.
4. **Pernyataan sertifikat persis 5.6**:
   - Penuh: `Peserta {nama/no} dinyatakan kompeten sebagai Junior Network Technician dengan predikat {predikat}.`
   - Sub: `Peserta {nama/no} dinyatakan kompeten pada sub kompetensi {sub} dengan predikat {predikat}.`
   - Unit: `Peserta {nama/no} dinyatakan kompeten pada unit {daftar unit lulus} dengan predikat {predikat}.`
   - Belum: `Peserta {nama/no} dinyatakan belum kompeten.`
   Gunakan nama peserta + nomor (mis. `Ahmad (03)`).
5. **Predikat juga berlaku untuk hasil "kompeten pada unit"** (5.5: rata-rata semua unit lulus).
6. **Kunci dengan indikator kosong**: izinkan bila asesor mengirim `confirm_empty=true` (kosong dihitung 0). Tanpa konfirmasi → 400 daftar indikator kosong. Ini tafsir "harus ditandai sebelum dikunci".
7. Nama hasil: `kompeten_penuh`, `kompeten_sub`, `kompeten_unit`, `belum_kompeten`.
8. Sub kompetensi & unit mengikuti tabel 5.3 persis (satu unit boleh di beberapa sub).

## 3. Stack & struktur
- Backend: FastAPI + SQLite WAL, Python 3.14, tanpa ORM berat (pakai `sqlite3` + row factory). Sajikan frontend statis dari `/`.
- Frontend: **vanilla ES modules + CSS**, tanpa build step, tanpa framework, tanpa CDN JS. Font Space Grotesk dari Google Fonts (dengan fallback).
- Satu service: `uvicorn app.main:app`.
- Struktur minimal:
```
app/
  .venv/
  main.py            # FastAPI app + routes
  db.py              # koneksi, migrasi, seed
  auth.py            # password hash, sesi, TOTP, rate limit
  rules.py           # perhitungan & keputusan (PURE functions)
  sheets.py          # sinkron Google Sheets
  backup.py          # backup & retensi
  seed_data.py       # 13 unit, 61 indikator, 5 sub kompetensi
  static/
    index.html
    app.css
    app.js
    sw.js
  tests/
    test_rules.py
    test_api.py
  README.md
  run.sh
```
- Semua waktu ISO-8601 UTC. Nominal uang tidak ada.
- ID publik pakai integer; jangan bocorkan path filesystem.

## 4. Data & seed
Tabel: `school`, `participant`, `unit`, `indicator`, `sub_competency`, `sub_competency_unit`, `assessment`, `score`, `config`, `sync_outbox`, `audit_log`, `user`, `session`.
- `unit.kode` = kode SKKNI; `judul`; `urutan`; `aktif`; `version`.
- `indicator.kode` = `IND-001`..`IND-061`; `unit_kode`; `teks`; `urutan`; `aktif`.
- `assessment`: participant_id, instrument_version, status (`in_progress`/`locked`), started_at, locked_at, unlock_reason, result_json.
- `score`: assessment_id, indicator_kode, value 0–3 NULL, note, updated_at, UNIQUE(assessment_id, indicator_kode).
- `config`: key/value JSON (threshold, predikat, templates, sheets id, dll).
- `sync_outbox`: idempotency_key UNIQUE, payload, status, retry_count, last_error.
- `audit_log`: append-only.

**Seed 13 unit / 61 indikator**:
- Unit & jumlah: 003(2), 004(2), 008(2), 009(3), 010(4), 011(13), 012(4), 006(11), 015(3), 020(9), 017(2), 018(2), 022(4).
- Sumber teks: `/tmp/opencode/subkomp.txt` (instrumen 22 unit, 59 indikator) dan garis besar.
- Petakan teks secara logis; bila ada slot yang tidak punya teks sumber, isi dengan teks fungsional yang jelas dan tambahkan catatan di README + UI Config: "Teks indikator usulan, wajib diverifikasi asesor (Q-101)". Jangan diam-diam mengarang seolah final.
- Sub kompetensi:
  - `SK-01 Perancang Jaringan Muda`: 003, 004
  - `SK-02 Teknisi Instalasi Jaringan`: 008, 009, 010, 011
  - `SK-03 Teknisi Konfigurasi Jaringan`: 004, 011, 012
  - `SK-04 Teknisi Keamanan & Trafik Jaringan`: 006, 015, 020
  - `SK-05 Teknisi Troubleshooting & Pemulihan`: 017, 018, 022
- Config default: `pass_threshold=70`, `predicate_sangat_mahir=90`, `predicate_mahir=80`, `predicate_cakap=70`.

## 5. Aturan perhitungan (implementasi persis, pure functions di `rules.py`)
- `unit_score = sum(skor)/ (3*n) * 100`, 2 desimal.
- `passed = skor*10 >= 21*n` (integer).
- `empty_count` = skor NULL.
- Semua 13 lulus → `kompeten_penuh`.
- Selain itu: sub terpenuhi bila semua unit penyusun lulus. Jika >1, pilih rata-rata persen unit penyusun tertinggi; seri → urutan sub teratas. Jika ada → `kompeten_sub`.
- Ada unit lulus tapi tidak ada sub → `kompeten_unit` (daftar unit lulus).
- Tidak ada unit lulus → `belum_kompeten`.
- Predikat = rata-rata persen **unit lulus**; >=90 Sangat Mahir, >=80 Mahir, >=70 Cakap.
- Hasil disimpan di `result_json`, dihitung ulang saat lock. Hasil assessment locked tidak berubah walau config berubah.

## 6. API (cookie session, prefix `/api`)
Auth:
- `GET /api/auth/status` → `{needs_setup, authenticated}`.
- `POST /api/auth/setup` `{username,password}` → buat user pertama, kembalikan `{otpauth_uri, secret}`. Tolak bila sudah ada user.
- `POST /api/auth/login` `{username,password,totp}` → set cookie sesi. Rate limit 5/menit/IP.
- `POST /api/auth/logout`.
- `GET /api/auth/me`.
Semua endpoint lain wajib sesi. Mutasi wajib header `X-Requested-With: fetch` (CSRF sederhana).
Sekolah/peserta:
- CRUD `/api/schools`, `/api/schools/{id}/participants`, `POST .../import` (CSV: nomor,nama,kelas; dukung `;` dan `,`; normalisasi; laporkan baris error & duplikat).
- `GET /api/schools/{id}/overview` → statistik status peserta + progres.
Penilaian:
- `POST /api/assessments` `{participant_id}` (idempoten: kembalikan yang ada).
- `GET /api/assessments/{id}` → assessment + units + indicators + scores + progress + result preview.
- `PATCH /api/assessments/{id}/scores` `{items:[{indicator_kode,value,note?}], client_ts?}` → upsert batch idempoten; tolak bila locked.
- `POST /api/assessments/{id}/lock` `{confirm_empty?}`.
- `POST /api/assessments/{id}/unlock` `{reason}` (min 10 karakter).
- `GET /api/assessments/{id}/result`.
Hasil/ekspor:
- `GET /api/schools/{id}/results`.
- `GET /api/schools/{id}/export?format=csv|xlsx` (CSV UTF-8 BOM; XLSX sheet Ringkasan, Detail Unit, Sub Kompetensi).
Config:
- `GET /api/config/instrument`, CRUD unit/indicator/sub-competency; setiap perubahan struktur menaikkan `version` dan mencatat audit.
Sync:
- `POST /api/sync/scores` (opsional; endpoint utama offline) dengan API key `X-API-Key` ATAU sesi.
- `GET /api/sync/status`, `POST /api/sync/sheets` (manual), `POST /api/admin/backup`, `GET /api/admin/backups`.
- `POST /api/sync/pull` tidak ada (satu arah).

## 7. Offline & frontend
- Service worker cache app shell (network-first untuk API, cache-first untuk aset).
- IndexedDB store `outbox`: `{key: assessment_id:indicator_kode, assessment_id, indicator_kode, value, note, ts}`.
- Setiap perubahan skor: tulis UI optimistis → simpan outbox → coba kirim batch; badge per indikator: `synced` / `pending` / `failed`.
- Saat `online`, flush otomatis tiap 15 detik + tombol "Sinkron sekarang".
- Konflik: last-write-wins berdasarkan `client_ts` (satu pengguna). Server menyimpan `updated_at`.
- Jangan memblokir input saat offline.
- Tampilkan banner "Offline — perubahan disimpan di perangkat".

## 8. UI — wajib mengikuti ini
**Referensi visual:** AeroPanel. **Minimalis, bukan AI slop.**
Tokens (CSS variables):
```
--bg:#f6f7f9; --surface:#ffffff; --surface-2:#fbfbfc;
--border:#e5e7eb; --text:#111827; --muted:#6b7280;
--primary:#4f46e5; --primary-soft:rgba(79,70,229,.08);
--success:#22c55e; --danger:#ef4444; --warning:#f59e0b; --info:#06b6d4;
--radius:12px; --radius-sm:8px;
--shadow:0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06);
```
Dark: `--bg:#14161a; --surface:#1b1e24; --surface-2:#20242b; --border:#2b3038; --text:#e5e7eb; --muted:#9ca3af;` primary tetap.
- Font: `Space Grotesk`, weights 400/500/600/700. Angka pakai `font-variant-numeric: tabular-nums`.
- Layout: sidebar 260px (collapsible), topbar 64px, content max 1200px, padding 24px. Mobile: sidebar jadi drawer, tabel scroll horizontal, tombol skor full-width grid.
- Komponen: card putih border 1px + shadow halus; tombol primary indigo radius 8px; tombol skor 0–3 segmented 44px; progress bar 8px dengan **penanda 70%**; badge status (hijau Lulus, merah Belum, amber kosong); tabel sticky header; modal kunci/buka kunci; toast ringkas.
- Halaman: Login/Setup; Dashboard (ringkasan + daftar sekolah); Sekolah (peserta, impor CSV, progres, tombol "Peserta berikutnya"); Penilaian (unit accordion, skor, % unit live, status, catatan, panel hasil + pernyataan, kunci); Hasil (rekap + ekspor); Config (unit/indikator/sub, versi); Sinkron/Backup.
- **Larangan:** gradien, glassmorphism, emoji, hero besar, ilustrasi AI, animasi berlebihan, teks placeholder "Lorem", ikon acak. Ikon boleh inline SVG sederhana atau tanpa ikon.
- Bahasa UI: Indonesia. Format tanggal `dd Mmm yyyy`.
- Aksesibilitas: label, fokus terlihat, kontras AA, target sentuh ≥44px.

## 9. Google Sheets & backup
- Sheets: service account dari env `GOOGLE_SERVICE_ACCOUNT_JSON` (path) + `GOOGLE_SHEETS_ID`. Tab per sekolah, sanitasi `[]:*?/\` dan maks 100 char, hindari nama sistem. Upsert berdasarkan (nomor peserta). Jika env tidak ada → status `disabled`, jangan crash. Tulis kolom sesuai garis besar 8.4.
- Backup: `POST /api/admin/backup` → `sqlite3` backup API ke `BACKUP_DIR` (default `./backups`), opsional enkripsi `openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_KEY` bila `BACKUP_KEY` ada. Retensi 30 hari. Sertakan `backup.sh` + contoh cron.
- Keamanan: header HSTS (bila secure), CSP, X-Frame-Options DENY, nosniff, Referrer-Policy. `robots.txt` disallow. Log tanpa nama/nilai siswa.

## 10. Tes & kriteria selesai
- `pytest` untuk `rules.py`: **semua 9 skenario bagian 11** + kasus batas 70% (24/33 lulus, 23/33 gagal) + predikat + seri sub + kosong.
- Tes API: login/setup, CRUD sekolah, impor CSV duplikat, mulai assessment, upsert skor idempoten, lock tanpa konfirmasi kosong (400), lock dengan konfirmasi, unlock alasan <10 (400), hasil per sekolah, ekspor CSV/XLSX, config version naik.
- `README.md`: cara jalan (`./run.sh`), env, setup TOTP, seed, backup, Sheets, deploy Caddy contoh.
- pastikan `./run.sh` benar-benar bisa start dan halaman login tampil.
- Jangan menyentuh file `01-riset.md`, `02-prd.md`, `04-qa.md`, `05-status.md`.

## 11. Jika tertahan
Tulis pertanyaan spesifik ke Orch di `03-build.md` bagian "Terblokir", jangan berhenti diam-diam. Laporkan: apa selesai, apa belum, cara menjalankan, hasil tes.
