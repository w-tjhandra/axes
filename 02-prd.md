# UKK Junior Network Technician — Assessment Platform PRD

**Versi:** v0.2  
**Tanggal:** 2026-11-06  
**Penulis:** Prada (Agent PRD)  
**Status:** Draft — Perlu Review Pengguna & Testability (Aqua)  
**Stakeholder:** Tim Akademi/Pelatihan, Asesor UKK, Koordinator Sekolah  
**Sumber Kebenaran:** Garis Besar PRD (13 Unit SKKNI, 61 Indikator, 5 Sub Kompetensi, Aturan 5.4/5.5/5.6)  
**Artefak Riset:** `01-riset.md` (belum ada)

---

## 1. Ringkasan

Platform penilaian UKK Junior Network Technician berbasis **VPS-centric** (FastAPI + SQLite WAL sebagai *source of truth*). Frontend SPA (PWA) + IndexedDB hanya sebagai antrean offline. Mendukung 13 Unit SKKNI (total 61 indikator, skor maks 183), 5 Sub Kompetensi, perhitungan & aturan kelulusan persis garis besar (5.4/5.5/5.6). Single-user (1 akun asesor + TOTP). MVP: login, sekolah, peserta, ujian per unit, kunci/buka kunci, hasil, ekspor, sinkron Sheets satu arah, backup terjadwal.

---

## 2. Latar Belakang & Masalah

**Masalah:**  
- Penilaian manual (kertas/Jotform) rawan kesalahan hitung, tidak terstruktur per SKKNI, tidak ada jejak audit.  
- Butuh implementasi aturan 5.4 (13 unit lulus → penuh; sub kompetensi terpenuhi jika semua unit lulus, pilih rata-rata tertinggi, seri urutan teratas; unit lulus tanpa sub → kompeten unit; tidak ada → belum kompeten).  
- Butuh predikat 5.5 (≥90 Sangat Mahir, 80–89 Mahir, 70–79 Cakap) dari rata-rata unit lulus.  
- Butuh pernyataan sertifikat 5.6.  
- Asesor butuh form per unit (skor 0–3, persen, status, penanda 70%, indikator kosong ditandai, hasil & pernyataan langsung, catatan).  
- Offline queue + sinkron idempoten saat koneksi pulih.

**Bukti:** Garis besar PRD (tabel 5.2 unit, 5.3 sub kompetensi, aturan 5.4/5.5/5.6, bagian 6 fitur MVP, 8.1 entitas, 11 skenario uji).

**Dampak jika tidak diselesaikan:** Ketidakkonsistenan nilai, tidak auditabel, asesor repot hitung manual, tidak bisa sinkron ke Sheets/backup otomatis.

---

## 3. Tujuan & Non-Tujuan

### 3.1 Tujuan (Goals) — Terukur

| ID | Tujuan | Target & Cara Ukur |
|----|--------|-------------------|
| G-01 | Asesor selesai input 1 peserta (61 indikator) ≤ 20 menit | Stopwatch UAT: median ≤ 20 menit dari buka form → klik "Kunci" |
| G-02 | Perhitungan otomatis 100% match aturan 5.4/5.5/5.6 | Unit test: 100% formula tercover, 0 perhitungan manual |
| G-03 | Setiap skor punya jejak audit (user, timestamp, versi instrumen) | Audit log table: 1 baris per skor per peserta, append-only |
| G-04 | Offline queue: input penuh tanpa internet, sinkron idempoten saat online | Test: putus koneksi → input 5 peserta → online → sinkron → 0 duplikat |
| G-05 | Ekspor CSV/Excel rekap per sekolah + sinkron Sheets satu arah per tab | Visual diff vs template ≤ 2%; Sheets idempoten (ulang tidak gandakan baris) |
| G-06 | Backup terjadwal (harian) ke storage VPS | Cron job jalan, file restoreable |

### 3.2 Non-Tujuan (Out of Scope) — Persis Garis Besar

- Multi-user concurrent editing (single asesor per akun).  
- Sinkron Sheets dua arah (hanya push dari server).  
- AI di jalur penulisan/penilaian.  
- Sertifikat resmi LSP/BNSP (hanya pernyataan 5.6 di PDF/HTML).  
- Manajemen soal/bank soal (instrumen fix 13 unit/61 indikator, editable via config).  
- Portal peserta login/lihat nilai sendiri.  
- Integrasi LMS/SIAKAD (export manual dulu).  
- Foto bukti (Tahap 2).  
- Multi-asesor per sekolah (Tahap 2).  
- RBAC lanjutan (Tahap 3).

---

## 4. Pengguna & Use Case

### 4.1 Persona

| Persona | Deskripsi | Kebutuhan Utama |
|---------|-----------|-----------------|
| **Asesor UKK** | Guru/industri bersertifikat, 1 akun + TOTP, mengawasi banyak sekolah | Login aman, pilih sekolah, input skor per unit cepat, lihat hasil & pernyataan langsung, kunci/buka kunci, ekspor |
| **Koordinator Sekolah** | Admin akademi, kelola daftar sekolah & peserta import CSV | CRUD sekolah, import peserta CSV, lihat rekap hasil per sekolah |
| **Sistem (Backend)** | FastAPI + SQLite WAL di VPS, cron backup & Sheets sync | Source of truth, idempotent sync, scheduled jobs |

### 4.2 User Stories (MVP)

| ID | Story | Prioritas |
|----|-------|-----------|
| US-01 | Sebagai **Asesor**, saya ingin **login 1 akun + TOTP** agar aman. | Must |
| US-02 | Sebagai **Koordinator**, saya ingin **CRUD Sekolah** (nama, kode, alamat, kontak) agar data terpusat. | Must |
| US-03 | Sebagai **Koordinator**, saya ingin **Import Peserta CSV per sekolah** (kolom: nisn, nama, kelas, jurusan) dengan deduplikasi NISN, normalisasi nama sekolah (huruf/spasi). | Must |
| US-04 | Sebagai **Asesor**, saya ingin **Beranda Ujian per Sekolah** menampilkan progres (unit selesai/total), daftar peserta, tombol "Peserta Berikutnya" (belum dinilai) agar navigasi cepat. | Must |
| US-05 | Sebagai **Asesor**, saya ingin **Form Penilaian per Unit** (13 unit): skor 0–3 per indikator, persen real-time, status Lulus/Tidak Lulus, penanda 70%, indikator kosong ditandai, hasil unit & pernyataan sertifikat 5.6 langsung, catatan asesor per unit. | Must |
| US-06 | Sebagai **Asesor**, saya ingin **Simpan Otomatis** (debounce 500ms) + antrean offline (IndexedDB) + indikator status sinkron (pending/synced/failed) agar tidak kehilangan data. | Must |
| US-07 | Sebagai **Asesor**, saya ingin **Kunci Ujian** (validasi: semua indikator terisi; jika tidak → dilarang) + **Buka Kunci** (wajib alasan, tercatat audit) agar kontrol integritas. | Must |
| US-08 | Sebagai **Koordinator**, saya ingin **Hasil per Sekolah**: rekap unit lulus/tidak, sub kompetensi terpenuhi/ranking, predikat 5.5, pernyataan 5.6, ekspor CSV/Excel. | Must |
| US-09 | Sebagai **Sistem**, saya ingin **Sinkron Sheets Satu Arah** per tab sekolah (sanitasi nama tab), idempoten (ulang tidak gandakan baris), dijalankan manual/terjadwal. | Must |
| US-10 | Sebagai **Sistem**, saya ingin **Backup Terjadwal Harian** (SQLite dump + config) ke storage VPS. | Must |
| US-11 | Sebagai **Admin**, saya ingin **Config CRUD** Unit/Indikator/SubKompetensi (versi instrumen: perubahan menaikkan versi, hasil lama pakai versi lama) agar bisa update tanpa deploy. | Must |
| US-12 | Sebagai **Asesor**, saya ingin **Dark/Light Mode**, UI minimalis AeroPanel, tombol skor ≥44px, bar nilai penanda 70%. | Should |

---

## 5. Metrik Sukses

| Metrik | Target | Cara Ukur |
|--------|--------|-----------|
| Waktu input per peserta | ≤ 20 menit (median) | Telemetri backend: `assessment.started_at` → `locked_at` |
| Akurasi perhitungan 5.4/5.5/5.6 | 100% match manual | Unit test 100 skenario kombinasi skor |
| Kehilangan data offline | 0 | Chaos test: offline input → online sync → 0 delta |
| Sinkron Sheets idempoten | 0 baris duplikat | Integrasi test: push 3× → row count = peserta × unit |
| Waktu generate hasil rekap | ≤ 2 detik per sekolah | Stopwatch API `/results/{school_id}` |
| Uptime VPS | ≥ 99.5% | Uptime monitor |

---

## 6. Requirement

### 6.1 Fungsional (FR)

#### 6.1.1 Autentikasi & Sekolah

| ID | Requirement | Prioritas | Sumber | Acceptance Criteria |
|----|-------------|-----------|--------|---------------------|
| FR-001 | Login email + password + TOTP (RFC 6238, 30s window), JWT access (15m) + refresh (7d), logout revoke refresh | Must | US-01 | Given kredensial benar + TOTP valid, When POST `/auth/login`, Then 200 + `{access, refresh}`; TOTP salah → 401; token expired → 401 refresh ok |
| FR-002 | CRUD Sekolah: `nama` (unik, normalisasi: trim, collapse spasi, title case), `kode` (unik, uppercase alnum), `alamat`, `kontak` | Must | US-02 | Given nama "  smk  negeri  1  ", When POST `/schools`, Then tersimpan sebagai "Smk Negeri 1", kode auto-generate dari nama jika kosong |
| FR-003 | List sekolah dengan paginasi, filter nama/kode, sort | Must | US-02 | GET `/schools?page=1&size=20&q=negeri` → 200 + data + meta |

#### 6.1.2 Peserta

| ID | Requirement | Prioritas | Sumber | Acceptance Criteria |
|----|-------------|-----------|--------|---------------------|
| FR-010 | CRUD Peserta per sekolah: `nisn` (unik per sekolah), `nama`, `kelas`, `jurusan`, `sekolah_id` | Must | US-03 | POST `/schools/{id}/participants` → 201; duplikat NISN → 409 |
| FR-011 | Import CSV Peserta: header `nisn,nama,kelas,jurusan`; validasi baris; transaksional (semua atau tidak ada); normalisasi nama sekolah dari konteks URL; response ringkasan (berhasil, gagal, duplikat) | Must | US-03 | Given CSV 30 baris, 2 duplikat NISN, 1 kolom kosong → 27 imported, 3 error detail (baris, alasan), 0 partial commit |
| FR-012 | Export CSV Peserta per sekolah | Should | US-03 | GET `/schools/{id}/participants/export` → `participants_{kode}_{tanggal}.csv` |

#### 6.1.3 Instrumen & Config (Versi Terkelola)

| ID | Requirement | Prioritas | Sumber | Acceptance Criteria |
|----|-------------|-----------|--------|---------------------|
| FR-020 | **Unit CRUD**: `kode` (unik, e.g. `UNIT-01`), `judul`, `urutan`, `aktif`, `indikator_count` (computed), `max_score = 3 * indikator_count`, `version` (integer, mulai 1). Perubahan struktur (tambah/hapus/ubah urutan indikator) → `version++`, data lama tetap pakai versi lama via `assessment.instrument_version`. | Must | US-11 | POST `/config/units` → 201; PUT `/config/units/{kode}` mengubah struktur → `version=2`, assessment baru pakai v2, lama tetap v1 |
| FR-021 | **Indikator CRUD** per unit: `kode` (unik global, e.g. `IND-001`), `unit_kode`, `teks`, `urutan`, `aktif`, `version` (ikuti unit). | Must | US-11 | POST `/config/units/{kode}/indicators` → 201; urutan unique per unit |
| FR-022 | **Sub Kompetensi CRUD**: `kode` (SK-01..SK-05), `judul`, `urutan`, `unit_kodes[]` (array kode unit penyusun, unik, minimal 1), `version`. Tabel 5.3 garis besar = seed data default. | Must | US-11 | POST `/config/sub-competencies` → 201; validasi `unit_kodes` semua ada & aktif |
| FR-023 | **Versi Instrumen**: endpoint `GET /config/instrument/version` return `{version, units_count, indicators_count, updated_at}`. Frontend tampilkan versi aktif di header. | Must | US-11 | Setelah seed default → version=1, units=13, indicators=61 |

#### 6.1.4 Penilaian (Assessment & Score)

| ID | Requirement | Prioritas | Sumber | Acceptance Criteria |
|----|-------------|-----------|--------|---------------------|
| FR-030 | **Start Assessment**: `POST /assessments` body `{participant_id, instrument_version}` → buat `Assessment` status `in_progress`, `started_at=now`, `instrument_version` = versi aktif (atau override). Return `assessment_id`. | Must | US-05 | Given peserta valid, When start, Then `Assessment` row + 61 `Score` rows (value=null, status=empty) terbuat, `instrument_version` Tercatat. |
| FR-031 | **Get Assessment Form per Unit**: `GET /assessments/{id}/units/{unit_kode}` → return unit detail + indikator (kode, teks, urutan) + skor existing (value 0-3/null, status, catatan). Indikator kosong (`value=null`) ditandai `empty=true`. | Must | US-05 | Response include `unit_progress: {filled, total, percent, passed}` (lulus jika `score*10 >= 21*n` integer). |
| FR-032 | **Upsert Score Batch per Unit**: `PATCH /assessments/{id}/units/{unit_kode}/scores` body `{scores: [{indicator_kode, value: 0-3, note}]}` → upsert `Score` rows, `updated_at=now`, hitung ulang unit status. Validasi: `value` integer 0-3. Return unit summary terbaru. | Must | US-05, US-06 | Given 5 indikator, kirim 3 skor → 3 updated, 2 tetap null. Unit `passed` dihitung: `sum(score)*10 >= 21*n` (n=5 → butuh total ≥11 → rata ≥2.2). |
| FR-033 | **Auto-save & Offline Queue**: Frontend simpan ke IndexedDB (outbox) tiap 500ms debounce. Sync ke backend saat online: `POST /sync/scores` batch idempoten `assessment_id+indicator_kode` (last-write-wins). Response `{synced, failed[]}`. Status sinkron per indikator: `pending`/`synced`/`failed` ditampilkan UI. | Must | US-06 | Offline: input 10 skor → IndexedDB 10 pending. Online: klik sync → 10 POST batch → 200, semua `synced`. Ulang sync → 0 duplikat (idempoten). |
| FR-034 | **Kunci Assessment**: `POST /assessments/{id}/lock` body `{force?: false}` → validasi: semua 61 indikator `value != null`. Jika ada kosong & `force=false` → 400 `{empty_indicators: [...]}`. Jika `force=true` (hanya admin) → kosong dihitung 0. Set `status=locked`, `locked_at=now`, `locked_by=user_id`. Hitung hasil final (5.4/5.5/5.6) simpan ke `Assessment.result_json`. | Must | US-07 | Lock sukses → 200 + `result_json` (unit_passed[], sub_competency_ranking[], predicate, certificate_statement). Lock gagal (ada kosong) → 400 detail. |
| FR-035 | **Buka Kunci**: `POST /assessments/{id}/unlock` body `{reason}` (wajib, min 10 char) → `status=in_progress`, `unlocked_at=now`, `unlocked_by`, `unlock_reason`, audit log. Hanya bisa jika `locked_at < 24 jam lalu` (configurable). | Must | US-07 | Unlock tanpa alasan → 400. Alasan tersimpan di `AuditLog`. Hasil final dihapus, skor tetap, bisa edit lagi. |

#### 6.1.5 Hasil & Rekap

| ID | Requirement | Prioritas | Sumber | Acceptance Criteria |
|----|-------------|-----------|--------|---------------------|
| FR-040 | **Hasil per Sekolah**: `GET /results/schools/{id}` → rekap: peserta list dengan `{unit_passed_count, unit_failed[], sub_competency_fulfilled[], predicate, certificate_statement, locked_at}`. Query param `status=locked|in_progress|all`. | Must | US-08 | Response < 2 detik untuk 100 peserta. `predicate` per 5.5: rata-rata persen unit lulus ≥90=Sangat Mahir, 80-89=Mahir, 70-79=Cakap. `certificate_statement` per 5.6. |
| FR-041 | **Ekspor CSV/Excel Rekap Sekolah**: `GET /results/schools/{id}/export?format=csv|xlsx` → file dengan sheet: Ringkasan, Detail Unit, Sub Kompetensi, Audit Lock/Unlock. | Must | US-08 | CSV: header `nisn,nama,kelas,unit_1_passed,...,predicate,statement,locked_at`. Excel: 4 sheet. |
| FR-042 | **Hasil Per Peserta (Detail)**: `GET /results/assessments/{id}` → lengkap: semua unit skor, persen, status, sub kompetensi ranking, predikat, pernyataan, catatan asesor, timeline lock/unlock. | Must | US-08 | Termasuk `instrument_version` yang dipakai. |

#### 6.1.6 Sinkron Sheets & Backup

| ID | Requirement | Prioritas | Sumber | Acceptance Criteria |
|----|-------------|-----------|--------|---------------------|
| FR-050 | **Sinkron Sheets Satu Arah**: `POST /sync/sheets` body `{school_id?, manual?: true}` → untuk setiap sekolah (atau sekolah_id), push ke Google Sheets: 1 tab per sekolah (nama tab = sanitasi `kode` alnum underscore, max 100 char), header fix, baris per peserta (nisn, nama, unit scores, predicate, statement, locked_at). Idempoten: `UPSERT` by `nisn` (update existing row). Response `{synced_schools, rows_upserted, duration_ms}`. | Must | US-09 | Sanitasi: "SMK 1/2" → "SMK_1_2". Ulang 3× → row count tidak bertambah. Error Sheets (quota/auth) → retry exponential backoff 1m/5m/15m, max 3×, log ke `SyncOutbox`. |
| FR-051 | **Backup Terjadwal**: Cron harian 02:00 WIB → dump SQLite (`.sql` + `.sqlite3` via `sqlite3 .dump`), zip + timestamp, simpan ke `/var/backups/ukk/`. Retensi 30 hari. Log ke `AuditLog` action `backup_completed`. | Must | US-10 | Manual trigger `POST /admin/backup` → 200 + path file. Restore test: file valid, schema match. |

#### 6.1.7 Audit & Sinkron Status

| ID | Requirement | Prioritas | Sumber | Acceptance Criteria |
|----|-------------|-----------|--------|---------------------|
| FR-060 | **Audit Log**: tabel `AuditLog` append-only: `id`, `timestamp`, `user_id`, `action`, `entity_type`, `entity_id`, `old_value`, `new_value`, `metadata` (JSON). Action: `login`, `assessment_start`, `score_upsert`, `assessment_lock`, `assessment_unlock`, `config_change`, `sheets_sync`, `backup`. | Must | Semua | Query `GET /audit?entity_type=assessment&entity_id={id}` → timeline lengkap. Tidak ada DELETE endpoint. |
| FR-061 | **Status Sinkron**: `GET /sync/status` → `{pending_scores, pending_sheets, last_scores_sync, last_sheets_sync, failed_items[]}`. Frontend tampilkan badge indikator per skor (pending/synced/failed). | Must | US-06 | Real-time via polling 30s atau SSE. |

---

### 6.2 Non-Fungsional (NFR)

| ID | Requirement | Target | Verifikasi |
|----|-------------|--------|------------|
| NFR-01 | **VPS-centric**: FastAPI + SQLite WAL source of truth. Frontend SPA + IndexedDB hanya offline queue. | 0 data loss saat sync | Integrasi test: kill frontend → data di IndexedDB → online → sync → DB match |
| NFR-02 | **Auth**: JWT RS256 (access 15m, refresh 7d, rotate), TOTP wajib, rate limit login 5/menit/IP | 0 brute force success | Pen test: 100 request → 429 |
| NFR-03 | **Performa API**: P95 < 200ms (skor upsert), < 500ms (hasil rekap 100 peserta), < 1s (Sheets sync 1 sekolah) | Load test k6 100 VU | CI gate |
| NFR-04 | **Database**: SQLite WAL mode, `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000;` | 0 lock contention | `PRAGMA integrity_check` berkala |
| NFR-05 | **Frontend PWA**: Installable, SW cache static, IndexedDB outbox (max 10k skor). Lighthouse PWA ≥ 90. | `npm run lighthouse` | CI |
| NFR-06 | **UI/UX**: Minimalis AeroPanel (detail bagian 7), dark/light, tombol skor ≥44px, bar nilai penanda 70%, font Space Grotesk. | 0 aksesibilitas critical (axe) | `npm run test:a11y` |
| NFR-07 | **Keamanan**: HTTPS only (VPS nginx + Let's Encrypt), CSP strict, input sanitasi (XSS), SQL injection impossible (parameterized), API key Sheets encrypted at rest (libsodium). | 0 CVE high/critical | `npm audit`, `trivy` scan |
| NFR-08 | **Observabilitas**: Structured JSON log (pino), metrics `/metrics` (Prometheus), health `/healthz`. | 100% request logged | Log sampling |
| NFR-09 | **Versi & Migrasi DB**: Alembic (atau manual SQL versioned). `instrument_version` di assessment menjamin hasil historis. | Migrasi naik/turun aman | Test migrasi v1→v2→v1 |
| NFR-10 | **Bundle Size**: JS gzipped ≤ 300 KB, CSS ≤ 30 KB. | `webpack-bundle-analyzer` | CI gate |

---

## 7. Desain UI/UX (Requirement)

**Referensi:** AeroPanel (dashboard minimalis, card-based, sidebar navigasi).  
**Palet:**  
- Primary: `#4f46e5` (Indigo 600)  
- Success: `#22c55e` (Green 500)  
- Danger: `#ef4444` (Red 500)  
- Warning: `#f59e0b` (Amber 500)  
- Info: `#06b6d4` (Cyan 500)  
- Border: `#e5e7eb` (Gray 200)  
- Page BG: `#f6f7f9` (Gray 50)  
- Surface: `#ffffff` (White)  
- Text: `#111827` (Gray 900)  
- Muted: `#6b7280` (Gray 500)  
- Dark mode: invert page/surface/text/muted, primary unchanged.

**Tipografi:** Space Grotesk (heading + UI), system UI fallback.  
**Layout:** Sidebar kiri 260px (collapsible 72px), Topbar 64px, Content area max-width 1200px centered. Card radius 12px, shadow `0 1px 3px rgba(0,0,0,0.08)`.  
**Komponen Kunci:**  
- **Skor Button Group** (0/1/2/3): target ≥44×44px, touch-friendly, active state primary, empty state muted border.  
- **Progress Bar Unit**: tinggi 8px, warna success/danger, **penanda 70%** (garis putih/tebal 2px di 70% lebar).  
- **Indikator Kosong**: badge "—" amber, tooltip "Belum diisi".  
- **Hasil Unit**: card ringkas: persen besar, status Lulus/Tidak Lulus, predikat jika semua unit lulus.  
- **Pernyataan Sertifikat 5.6**: card surface, border-left primary 4px, teks justification, copy button.  
- **Kunci/Buka Kunci**: modal konfirmasi, unlock wajib textarea alasan (min 10 char, char counter).  
- **Sinkron Badge**: per indikator (⏳ pending, ✓ synced, ⚠ failed), global topbar (🟢/🟡/🔴).  
- **Tabel Rekap**: virtualized (react-window), sort/filter, sticky header, export button sticky bottom.  
- **Tidak ada:** gradien besar, glassmorphism, emoji di UI, hero section, animasi berlebihan.

---

## 8. Data Model (SQLite Schema — Source of Truth)

```sql
-- ==================== CONFIG (Versi Terkelola) ====================
CREATE TABLE unit (
  kode TEXT PRIMARY KEY,           -- UNIT-01..UNIT-13
  judul TEXT NOT NULL,
  urutan INTEGER NOT NULL UNIQUE,
  aktif INTEGER NOT NULL DEFAULT 1, -- 0/1
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE indicator (
  kode TEXT PRIMARY KEY,           -- IND-001..IND-061
  unit_kode TEXT NOT NULL REFERENCES unit(kode),
  teks TEXT NOT NULL,
  urutan INTEGER NOT NULL,
  aktif INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  UNIQUE(unit_kode, urutan)
);

CREATE TABLE sub_competency (
  kode TEXT PRIMARY KEY,           -- SK-01..SK-05
  judul TEXT NOT NULL,
  urutan INTEGER NOT NULL UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE sub_competency_unit (
  sub_competency_kode TEXT NOT NULL REFERENCES sub_competency(kode),
  unit_kode TEXT NOT NULL REFERENCES unit(kode),
  PRIMARY KEY (sub_competency_kode, unit_kode)
);

-- ==================== SEKOLAH & PESERTA ====================
CREATE TABLE school (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kode TEXT NOT NULL UNIQUE,       -- SMK_NEGERI_1
  nama TEXT NOT NULL,              -- normalized title case
  alamat TEXT,
  kontak TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE participant (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_id INTEGER NOT NULL REFERENCES school(id),
  nisn TEXT NOT NULL,
  nama TEXT NOT NULL,
  kelas TEXT,
  jurusan TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(school_id, nisn)
);

-- ==================== PENILAIAN ====================
CREATE TABLE assessment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  participant_id INTEGER NOT NULL REFERENCES participant(id),
  instrument_version INTEGER NOT NULL, -- versi unit/indicator saat start
  status TEXT NOT NULL DEFAULT 'in_progress', -- in_progress, locked
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  locked_at TEXT,
  locked_by INTEGER,               -- user id (single user = 1)
  unlocked_at TEXT,
  unlocked_by INTEGER,
  unlock_reason TEXT,
  result_json TEXT,                -- JSON hasil final (5.4/5.5/5.6)
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE score (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL REFERENCES assessment(id),
  indicator_kode TEXT NOT NULL REFERENCES indicator(kode),
  value INTEGER,                   -- 0,1,2,3 atau NULL (kosong)
  note TEXT,                       -- catatan asesor per indikator
  synced INTEGER NOT NULL DEFAULT 0, -- 0=pending, 1=synced, 2=failed
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(assessment_id, indicator_kode)
);

-- ==================== SYNC OUTBOX (Idempoten) ====================
CREATE TABLE sync_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  payload_type TEXT NOT NULL,      -- 'score', 'sheets', 'backup'
  payload_json TEXT NOT NULL,      -- full payload
  idempotency_key TEXT NOT NULL,   -- e.g. 'score:assessment_id:indicator_kode'
  status TEXT NOT NULL DEFAULT 'pending', -- pending, processing, done, failed
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  processed_at TEXT,
  UNIQUE(idempotency_key)
);

-- ==================== AUDIT LOG ====================
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL DEFAULT (datetime('now')),
  user_id INTEGER NOT NULL DEFAULT 1,
  action TEXT NOT NULL,            -- login, assessment_start, score_upsert, assessment_lock, assessment_unlock, config_change, sheets_sync, backup
  entity_type TEXT NOT NULL,       -- assessment, score, unit, indicator, sub_competency, school, participant
  entity_id TEXT NOT NULL,         -- PK string/int
  old_value TEXT,                  -- JSON
  new_value TEXT,                  -- JSON
  metadata TEXT                    -- JSON (e.g. {ip, user_agent})
);

-- ==================== INDEXES ====================
CREATE INDEX idx_score_assessment ON score(assessment_id);
CREATE INDEX idx_score_synced ON score(synced) WHERE synced=0;
CREATE INDEX idx_assessment_participant ON assessment(participant_id);
CREATE INDEX idx_participant_school ON participant(school_id);
CREATE INDEX idx_sync_outbox_status ON sync_outbox(status) WHERE status IN ('pending','processing');
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
```

---

## 9. API Specification (FastAPI — Source of Truth)

**Base URL:** `https://api.ukk.example.com/api/v1`  
**Auth:** `Authorization: Bearer <access_token>` (semua endpoint kecuali `/auth/*`).  
**Rate Limit:** 120 req/menit per IP (login 5/menit).  
**Idempotency:** Header `Idempotency-Key` untuk POST/PATCH (opsional tapi disarankan).

### 9.1 Auth

| Method | Path | Body | Response |
|--------|------|------|----------|
| `POST` | `/auth/login` | `{email, password, totp}` | `{access_token, refresh_token, token_type: "bearer", expires_in: 900}` |
| `POST` | `/auth/refresh` | `{refresh_token}` | `{access_token, expires_in: 900}` |
| `POST` | `/auth/logout` | `{refresh_token}` | `204` (revoke refresh) |
| `GET` | `/auth/me` | — | `{id, email, totp_enabled, role}` |

### 9.2 Schools

| Method | Path | Body/Query | Response |
|--------|------|------------|----------|
| `GET` | `/schools` | `?page=1&size=20&q=&sort=nama:asc` | `{data: School[], meta: {page,size,total}}` |
| `POST` | `/schools` | `{nama, kode?, alamat, kontak}` | `School` (201) |
| `GET` | `/schools/{id}` | — | `School` |
| `PATCH` | `/schools/{id}` | `{nama?, alamat?, kontak?}` | `School` |
| `DELETE` | `/schools/{id}` | — | `204` (jika tidak ada peserta/assessment) |
| `GET` | `/schools/{id}/participants/export` | `?format=csv|xlsx` | File download |

### 9.3 Participants

| Method | Path | Body/Query | Response |
|--------|------|------------|----------|
| `GET` | `/schools/{school_id}/participants` | `?page=1&size=50&q=` | `{data: Participant[], meta}` |
| `POST` | `/schools/{school_id}/participants` | `{nisn, nama, kelas, jurusan}` | `Participant` (201) |
| `POST` | `/schools/{school_id}/participants/import` | `multipart/form-data` file CSV | `{imported: 27, errors: [{row, field, message}], duplicates: [{nisn, row}]}` |
| `GET` | `/schools/{school_id}/participants/{id}` | — | `Participant` |
| `PATCH` | `/schools/{school_id}/participants/{id}` | `{nama?, kelas?, jurusan?}` | `Participant` |
| `DELETE` | `/schools/{school_id}/participants/{id}` | — | `204` |

### 9.4 Config (Instrument)

| Method | Path | Body/Query | Response |
|--------|------|------------|----------|
| `GET` | `/config/instrument/version` | — | `{version, units_count, indicators_count, sub_competencies_count, updated_at}` |
| `GET` | `/config/units` | `?aktif=true` | `Unit[]` |
| `POST` | `/config/units` | `{kode, judul, urutan, aktif?}` | `Unit` (201, version++) |
| `GET` | `/config/units/{kode}` | — | `Unit + indicators[]` |
| `PATCH` | `/config/units/{kode}` | `{judul?, urutan?, aktif?}` | `Unit` (jika struktur berubah → version++) |
| `DELETE` | `/config/units/{kode}` | — | `204` (jika tidak dipakai assessment) |
| `GET` | `/config/units/{kode}/indicators` | — | `Indicator[]` |
| `POST` | `/config/units/{kode}/indicators` | `{kode, teks, urutan, aktif?}` | `Indicator` (201) |
| `PATCH` | `/config/indicators/{kode}` | `{teks?, urutan?, aktif?}` | `Indicator` |
| `DELETE` | `/config/indicators/{kode}` | — | `204` |
| `GET` | `/config/sub-competencies` | — | `SubCompetency + units[]` |
| `POST` | `/config/sub-competencies` | `{kode, judul, urutan, unit_kodes[]}` | `SubCompetency` (201) |
| `PATCH` | `/config/sub-competencies/{kode}` | `{judul?, urutan?, unit_kodes[]?}` | `SubCompetency` |
| `DELETE` | `/config/sub-competencies/{kode}` | — | `204` |

### 9.5 Assessment & Scores

| Method | Path | Body/Query | Response |
|--------|------|------------|----------|
| `POST` | `/assessments` | `{participant_id, instrument_version?}` | `Assessment + scores[]` (201, 61 skor null) |
| `GET` | `/assessments/{id}` | — | `Assessment + unit_progress[]` |
| `GET` | `/assessments/{id}/units/{unit_kode}` | — | `{unit, indicators[], scores[], unit_progress}` |
| `PATCH` | `/assessments/{id}/units/{unit_kode}/scores` | `{scores: [{indicator_kode, value: 0-3, note?}]}` | `{unit_progress, scores[]}` |
| `POST` | `/assessments/{id}/lock` | `{force?: false}` | `{result_json, locked_at}` |
| `POST` | `/assessments/{id}/unlock` | `{reason}` | `{unlocked_at}` |
| `GET` | `/assessments/{id}/result` | — | `result_json` (hanya jika locked) |

### 9.6 Results & Export

| Method | Path | Query | Response |
|--------|------|-------|----------|
| `GET` | `/results/schools/{school_id}` | `?status=locked|in_progress|all&page=1&size=50` | `{data: AssessmentResult[], meta}` |
| `GET` | `/results/schools/{school_id}/export` | `?format=csv|xlsx` | File download |
| `GET` | `/results/assessments/{id}` | — | `AssessmentResultDetail` |

### 9.7 Sync & Backup

| Method | Path | Body | Response |
|--------|------|------|----------|
| `POST` | `/sync/scores` | `{items: [{assessment_id, indicator_kode, value, note, client_timestamp}]}` | `{synced: 10, failed: []}` (idempoten per `assessment_id:indicator_kode`) |
| `GET` | `/sync/status` | — | `{pending_scores, pending_sheets, last_scores_sync, last_sheets_sync, failed_items[]}` |
| `POST` | `/sync/sheets` | `{school_id?, manual?: true}` | `{synced_schools, rows_upserted, duration_ms}` |
| `POST` | `/admin/backup` | — | `{path, size_bytes, timestamp}` |
| `GET` | `/admin/backups` | — | `{backups: [{path, size, created_at}]}` |

### 9.8 Audit

| Method | Path | Query | Response |
|--------|------|-------|----------|
| `GET` | `/audit` | `?entity_type=&entity_id=&action=&from=&to=&page=1&size=100` | `{data: AuditLog[], meta}` |

---

## 10. Business Rules (Aturan Bisnis — Persis Garis Besar)

### 10.1 Perhitungan Unit (5.4)

- **Nilai unit** = `total_skor / (3 × n_indikator) × 100` (persen, 2 desimal).  
- **Lulus unit** bila `total_skor × 10 ≥ 21 × n_indikator` (integer arithmetic, hindari floating point).  
  - Contoh: n=5 → butuh total_skor ≥ 11 (11×10=110 ≥ 105).  
- **Indikator kosong** (`value=null`) = **0** dan ditandai `empty=true` sebelum kunci.  
- **Kunci dilarang** jika ada indikator kosong (`force=false`). `force=true` hanya admin (kosong→0).

### 10.2 Kelulusan & Sub Kompetensi (5.4)

1. **13 unit semua Lulus** → **Kompeten Penuh**.  
2. **Sub Kompetensi Terpenuhi** bila **semua unit penyusunnya Lulus**.  
3. Jika >1 sub kompetensi terpenuhi → pilih **rata-rata persen unit lulus tertinggi**.  
4. Jika seri rata-rata → pilih **urutan teratas** (urutan sub kompetensi tabel 5.3).  
5. Jika **tidak ada sub kompetensi terpenuhi** tapi ada unit lulus → **Kompeten pada unit-unit tersebut** (sebutkan kode unit).  
6. Jika **tidak ada unit lulus** → **Belum Kompeten**.

### 10.3 Predikat (5.5)

- Hanya dihitung dari **unit yang Lulus**.  
- `rata_rata_persen = AVG(persen_unit_lulus)`.  
- ≥ 90 → **Sangat Mahir**  
- 80–89 → **Mahir**  
- 70–79 → **Cakap**  
- < 70 → (tidak mungkin karena unit lulus minimal 70%, tapi jika logika berubah → **Tidak Memenuhi**)

### 10.4 Pernyataan Sertifikat (5.6)

> "Berdasarkan hasil penilaian UKK Junior Network Technician, peserta **[NAMA]** (NISN: **[NISN]**) dari **[NAMA SEKOLAH]** dinyatakan **[KOMPETEN PENUH / KOMPETEN PADA UNIT ... / BELUM KOMPETEN]** dengan predikat **[SANGAT MAHIR / MAHIR / CAKAP]**."

- Jika Kompeten Penuh → sertakan predikat.  
- Jika Kompeten pada unit → sertakan daftar unit, **tanpa predikat**.  
- Jika Belum Kompeten → **tanpa predikat**.

### 10.5 Versi Instrumen

- Setiap `assessment` mencatat `instrument_version` saat `start`.  
- Perubahan config (unit/indikator/subkompetensi) → `version++` di tabel config.  
- Hasil assessment lama **tidak berubah** (masih pakai versi lama).  
- Frontend tampilkan badge versi di header: `v{instrument_version}`.

### 10.6 Sinkron Idempoten

- Key: `assessment_id:indicator_kode` (skor), `school_id:nisn` (Sheets).  
- Last-write-wins (timestamp client `client_timestamp` tie-breaker).  
- `sync_outbox` tabel antrean dengan `idempotency_key` unik.  
- Retry: 1m, 5m, 15m, 1h, max 24 jam lalu alert.

---

## 11. Acceptance Criteria (Mapping Skenario Uji Bagian 11)

| Skenario | Given | When | Then | AC ID |
|----------|-------|------|------|-------|
| **S-01 Login TOTP** | User registered, TOTP enrolled | POST `/auth/login` dengan TOTP valid | 200 + access+refresh token | AC-001 |
| | | TOTP salah (off by 1) | 401 `{error: "invalid_totp"}` | AC-002 |
| | | Token expired, refresh valid | POST `/auth/refresh` → 200 new access | AC-003 |
| **S-02 Sekolah CRUD** | - | POST `/schools` nama "  smk  1  " | 201, `nama="Smk 1"`, `kode="SMK_1"` | AC-010 |
| | School exists | POST duplicate `kode` | 409 `{error: "kode_exists"}` | AC-011 |
| **S-03 Import Peserta** | School exists | POST `/schools/{id}/participants/import` CSV 30 baris, 2 duplikat NISN, 1 kolom kosong | 200 `{imported:27, errors:3, duplicates:2}`; 0 partial | AC-020 |
| | | CSV header salah (tidak ada nisn) | 400 `{error: "invalid_header", required: ["nisn","nama"]}` | AC-021 |
| | | NISN duplikat di CSV itu sendiri | errors include both rows, imported 0 untuk duplikat | AC-022 |
| **S-04 Beranda Ujian** | School dengan 50 peserta, 10 locked, 20 in_progress, 20 belum start | GET `/results/schools/{id}?status=all` | Progress: 30/50 unit avg, daftar peserta + status, tombol "Berikutnya" → assessment in_progress paling atas | AC-030 |
| **S-05 Form Penilaian per Unit** | Assessment started, unit UNIT-01 (5 indikator) | GET `/assessments/{id}/units/UNIT-01` | 5 indikator dengan skor null, `empty=true`, progress 0/5, bar 0% penanda 70% | AC-040 |
| | | PATCH scores 3 indikator (2,3,1) | unit_progress: `filled=3, total=5, percent=40%, passed=false` (total=6 < 11) | AC-041 |
| | | Isi sisa 2 indikator (3,2) → total=11 | `passed=true` (11×10=110 ≥ 105), badge Lulus hijau | AC-042 |
| | | Indikator kosong tetap null saat lock | Lock → 400 `{empty_indicators: ["IND-003"]}` | AC-043 |
| **S-06 Auto-save & Offline** | Offline (network disconnected) | Input 10 skor di 2 unit | IndexedDB outbox 10 items `pending`, UI badge ⏳ | AC-050 |
| | Online kembali | Klik "Sinkron" / auto 30s | POST `/sync/scores` batch 10 → 200 `{synced:10}`, semua badge ✓ | AC-051 |
| | Ulang klik sinkron | POST batch sama | `{synced:10, failed:[]}` (idempoten, 0 duplikat) | AC-052 |
| | Sync gagal (server 500) | Retry exponential | status `failed` → retry 1m → 5m → 15m, max 3× lalu alert | AC-053 |
| **S-07 Kunci/Buka Kunci** | Assessment semua 61 indikator terisi | POST `/assessments/{id}/lock` | 200, `status=locked`, `result_json` berisi 5.4/5.5/5.6, `locked_at` set | AC-060 |
| | Ada 1 indikator kosong, force=false | POST lock | 400 `{empty_indicators: [...]} ` | AC-061 |
| | Locked, unlock tanpa alasan | POST unlock `{reason: ""}` | 400 `{error: "reason_required"}` | AC-062 |
| | Locked, unlock dengan alasan "salah input unit 5" | POST unlock `{reason: "salah input unit 5"}` | 200, `status=in_progress`, `unlock_reason` tersimpan, audit log `assessment_unlock`, `result_json` dihapus | AC-063 |
| **S-08 Hasil & Rekap** | School 5 peserta locked | GET `/results/schools/{id}` | 5 baris: unit_passed_count, sub_competency_fulfilled[], predicate, statement, locked_at | AC-070 |
| | | GET export CSV | File: header benar, 5 baris data, encoding UTF-8 | AC-071 |
| | | GET export XLSX | 4 sheet: Ringkasan, Detail Unit, Sub Kompetensi, Audit | AC-072 |
| **S-09 Sinkron Sheets** | 1 sekolah, 3 peserta locked | POST `/sync/sheets` `{school_id}` | Sheets tab `SMK_NEGERI_1` 3 baris + header, idempoten (ulang 3× → tetap 3 baris) | AC-080 |
| | Nama sekolah "SMK 1/2" | Sync | Tab name `SMK_1_2` (sanitasi alnum underscore) | AC-081 |
| | Sheets quota exceeded | Sync | Retry backoff, log `SyncOutbox` status `failed`, alert UI | AC-082 |
| **S-10 Backup** | - | POST `/admin/backup` | 200 `{path: "/var/backups/ukk/backup_20261106_020000.zip", size: 102400}` | AC-090 |
| | Cron 02:00 | Otomatis | File ada, `sqlite3 .dump` valid, retensi 30 hari | AC-091 |
| **S-11 Config Versi** | Instrument v1 (13 unit, 61 indikator) | PATCH `/config/units/UNIT-01` tambah 1 indikator | `version=2`, assessment baru pakai v2, assessment lama tetap v1 | AC-100 |
| **S-12 Offline→Online** | Offline input 5 peserta (300 skor) | Online, auto sync | Semua 300 skor `synced=1`, `SyncOutbox` done, 0 data loss | AC-110 |

---

## 12. Keputusan (Orch — Sudah Diputus, Tidak Dibuka Lagi)

| ID | Keputusan | Detail |
|----|-----------|--------|
| Q-002 | **Tidak Dikerjakan = 0 denominator penuh** | Indikator kosong dihitung 0 di pembilang **dan** masuk denominator (n = total indikator unit). |
| Q-004 | **Dependensi tidak ditegakkan di MVP** | Hanya peringatan UI (opsional), matriks dependensi ditunda Tahap 2. |
| — | **Bobot indikator sama (1 each)** | Skor 0–3 per indikator, total unit = Σ skor. |
| — | **Ambang 70% integer** | `total_skor × 10 ≥ 21 × n` (hindari float). |
| — | **Foto bukti tidak di MVP** | Tahap 2. |
| — | **Auth sync = static bearer API key** | Sheets API key disimpan encrypted (libsodium) di server, tidak di frontend. |
| — | **Tidak ada risiko kuota foto di MVP** | Karena tidak ada foto. |
| — | **Single asesor per akun** | Tidak perlu locking row, last-write-wins cukup. |
| — | **SQLite WAL source of truth** | Frontend IndexedDB hanya outbox. |
| — | **Sheets satu arah, per tab sekolah** | Sanitasi nama tab, idempoten by NISN. |

---

## 13. Pertanyaan Terbuka (Hanya Yang Benar-Benar Tersisa)

| ID | Pertanyaan | Konteks | Target Keputusan |
|----|------------|---------|------------------|
| Q-101 | **Teks final 61 indikator** (versi Bahasa Indonesia resmi) | Seed data `indicator.teks` butuh final sebelum MVP | Sebelum sprint 1 |
| Q-102 | **Verifikasi kode unit** (UNIT-01..UNIT-13) cocok SKKNI 2024/2025? | Tabel 5.2 garis besar vs SKKNI resmi | Sebelum sprint 1 |
| Q-103 | **Apakah Tes Pengetahuan (teori) masuk MVP?** | Garis besar hanya praktek (61 indikator). Jika ya → tambah entitas `knowledge_test` | Minggu 1 |
| Q-104 | **Format sertifikat PDF/HTML** (template, logo, QR verifikasi, tanda tangan digital) | Butuh desain final untuk `GET /results/assessments/{id}/certificate` | Sprint 2 |
| Q-105 | **Klien ACME/Let's Encrypt** untuk HTTPS VPS (nginx + certbot otomatis, atau Caddy)? | Infrastructure decision | Sprint 1 |

---

## 14. Rencana Rilis (Persis Garis Besar)

| Fase | Cakupan | Target |
|------|---------|--------|
| **MVP (Tahap 1)** | Login TOTP, Sekolah, Peserta Import, Assessment per Unit (13 unit, 61 indikator), Auto-save + Offline Queue + Sync, Kunci/Buka Kunci, Hasil 5.4/5.5/5.6, Export CSV/XLSX, Sheets Sync Satu Arah, Backup Harian, Config Versi, Audit Log, UI AeroPanel Dark/Light | 2026-12-15 |
| **Tahap 2** | Foto bukti per indikator (upload/compress), Multi-asesor per sekolah (RBAC dasar), Notifikasi real-time (SSE/WebSocket), Template sertifikat PDF + QR verifikasi, Dashboard analitik (tren, heatmap unit) | 2027-03-31 |
| **Tahap 3** | RBAC lanjutan (Admin/Koordinator/Asesor), Audit log ekspor & retention policy, Sinkron Sheets dua arah (opsional), Multi-UKK (instrumen lain), API publik untuk LMS/SIAKAD, Hardening keamanan (pen test, CSP, rate limit lanjutan) | 2027-06-30 |

---

## 15. Non-Goal (Persis Garis Besar)

- Multi-user concurrent editing pada assessment yang sama.  
- Sinkron Google Sheets dua arah (pull dari Sheets).  
- AI/ML di jalur penulisan/penilaian.  
- Sertifikat resmi LSP/BNSP (hanya pernyataan 5.6).  
- Manajemen bank soal terpisah.  
- Portal peserta (login, lihat nilai, banding).  
- Integrasi langsung LMS/SIAKAD (export manual dulu).  
- Offline-first sebagai arsitektur utama (hanya queue).

---

## 16. Changelog v0.1 → v0.2

| Area | v0.1 (Salah) | v0.2 (Benar — Garis Besar) |
|------|--------------|----------------------------|
| **Model Data** | 49 item Jotform, 5 sub A–E, 22 unit | 13 Unit SKKNI, 61 Indikator, 5 Sub Kompetensi (tabel 5.2/5.3) |
| **Aturan Hasil** | Bobot item, MoSCoW, override manual | 5.4 (13 lulus→penuh, sub kompetensi ranking, seri urutan, unit lulus, belum kompeten), 5.5 predikat dari rata-rata unit lulus, 5.6 pernyataan sertifikat |
| **Perhitungan** | Persen bebas, null=dikecualikan | `skor/(3×n)×100`, lulus `skor×10 ≥ 21×n` integer, kosong=0 denominator penuh |
| **Arsitektur** | Local-first IndexedDB utama | **VPS-centric** FastAPI + SQLite WAL source of truth; Frontend SPA + IndexedDB hanya offline queue |
| **Fitur MVP** | Sesi/laptop, 49 item, foto bukti, PDF template | Login TOTP, Sekolah, Peserta Import, 13 Unit form, Auto-save+Offline+Sync, Kunci/Buka, Hasil 5.4/5.5/5.6, Export, Sheets 1-arah, Backup, Config Versi |
| **API & DB** | Tidak lengkap, tidak konsisten | Lengkap: 8 entitas (School, Participant, Unit, Indicator, SubCompetency, SubCompetencyUnit, Assessment, Score, Config, SyncOutbox, AuditLog) + 40+ endpoint |
| **Keputusan Orch** | 15 pertanyaan terbuka | 7 keputusan tetap (Q-002, Q-004, bobot, ambang, foto, auth sync, kuota), 5 pertanyaan tersisa (Q-101..Q-105) |
| **UI** | Tidak ada spesifikasi | AeroPanel referensi, palet, font Space Grotesk, layout sidebar/topbar, skor button ≥44px, bar 70%, dark/light, minimalis |
| **Skenario Uji** | 87 AC generik | 11 skenario (S-01..S-12) dipetakan ke 30+ AC spesifik (AC-001..AC-110) |
| **Non-Goal** | Berbeda | Persis garis besar (multi-user, 2-arah Sheets, AI, sertifikat resmi, dll) |

---

**File PRD:** `/home/chandra/workspace/ukk-junior-network-tech/02-prd.md` (v0.2, ~650 baris)

**Siap untuk:** Review Pengguna → Testability Aqua → Deco Sprint 1 (MVP target 2026-12-15).

**Pertanyaan tersisa butuh jawaban minggu ini:** Q-101 (teks 61 indikator), Q-102 (kode unit), Q-103 (tes teori), Q-104 (format sertifikat), Q-105 (ACME client).
