# Brief untuk Deco — T-004 Perbaiki Bug QA

## 1. Konteks
QA sudah selesai (`../04-qa.md`). Hasil: **No-Go** karena 2 Major + 1 Minor blokir.
Gunakan DB yang sama (`data/ukk.db`) atau buat baru; aturan perhitungan **tidak disentuh**.

## 2. Bug yang wajib diperbaiki (P1)

### BUG-001 Major — Tabel overflow horizontal di mobile (390px)
**File:** `static/app.css`, `static/app.js` (render tabel)
**Masalah:** Di viewport ≤480px, `<table>` melebihi lebar layar; kolom aksi/skor ikut ke-scroll horizontal penuh; pengguna tidak menemukan tombol "Buka" atau skor.
**Perbaikan:**
- Wrapper tabel: `<div class="table-wrap">` dengan `overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100%`.
- Header tabel `position:sticky; left:0` (kolom pertama) dan `right:0` (kolom aksi) agar selalu terlihat saat scroll horizontal.
- Atau breakpoint ≤640px: ubah rendering sekolah/peserta dari tabel → card/accordion (satu baris = satu card, aksi di bawah).
- Pastikan tidak ada `white-space:nowrap` yang memaksa lebar.

### BUG-002 Major — Accordion unit tidak buka di mobile (touch)
**File:** `static/app.js` (render assessment), `static/app.css`
**Masalah:** Di `#/assessment/{id}` mobile, klik header unit tidak memperluas daftar indikator.
**Perbaikan:**
- Pakai `<details><summary>` native HTML untuk accordion unit (tidak butuh JS toggle, kerja di touch/keyboard otomatis).
- Atau pastikan event listener `click` + `touchstart` (passive) terpasang pada header unit.
- Cek CSS: `summary::-webkit-details-marker { display:none; }` + custom arrow; `details[open] summary` style.
- Pastikan `pointer-events:none` tidak ada di ancestor.

### BUG-003 Minor — Sekolah duplikat setelah normalisasi nama
**File:** `main.py` (POST `/schools`), `db.py`
**Masalah:** `normalize_school_name().title()` membuat `SMK 1` & `smk  1` jadi sama `Smk 1`, tapi cek duplikat pakai `kode` (slug) → 2 baris dibuat.
**Perbaikan:**
- Tambah unique index: `CREATE UNIQUE INDEX idx_school_nama_norm ON school(lower(replace(nama,'  ',' ')))` (normalisasi spasi ganda + lower).
- Atau di API: sebelum insert, cek `SELECT 1 FROM school WHERE lower(replace(nama,'  ',' ')) = lower(replace(?,'  ',' '))`.
- Return 409 `{error:"nama_exists", existing_id:...}`.

## 3. Bug P2 (bisa di batch sama)

### BUG-004 Minor — Badge sinkron topbar tidak update real-time setelah flush
**File:** `static/app.js` → `flushOutbox()` panggil `updateSyncPill()` di akhir (success & partial).

### BUG-005 Minor — Modal unlock tanpa counter karakter
**File:** `static/app.js` → template modal unlock: tambah `<div class="char-count"><span id="unlock-len">0</span>/10</div>`; update on `input`; merah jika <10.

## 4. Verifikasi setelah perbaiki
1. Jalankan `pytest -q` → 21 passed.
2. Start server port 8767.
3. Playwright mobile (390×844):
   - Login → Dashboard → Sekolah (tabel/card tidak overflow, aksi terlihat).
   - Tambah sekolah duplikat nama → 409.
   - Buka assessment → accordion unit buka/tutup via touch.
   - Kunci → unlock modal counter merah <10, hijau ≥10.
   - Offline → ubah skor → badge pending → online → flush → badge Tersinkron.
4. Screenshot mobile sebelum/sesudah simpan ke `/tmp/opencode/qa-shots/fix-*.png`.

## 5. Output
- Update `app/static/app.css`, `app/static/app.js`, `app/main.py`, `app/db.py` (index).
- Tulis ringkasan perbaikan ke `03-build.md` bagian "Perbaikan pasca-QA".
- Balas: status, file diubah, hasil pytest, verifikasi mobile OK/Tidak.