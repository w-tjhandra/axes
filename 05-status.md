# Papan Status — Platform Penilaian UKK

Permintaan : Platform penilaian UKK Junior Network Technician
Status     : **Siap rilis (GO QA)**
Workspace  : /home/chandra/workspace/ukk-junior-network-tech

| ID | Sub-task | Agent | Status | Artefak |
|---|---|---|---|---|
| T-001 | Detail PRD (revisi sesuai garis besar) | prada | **Selesai** | 02-prd.md v0.2 |
| T-002 | Bangun MVP (backend + frontend + seed) | deco | **Selesai** | app/ |
| T-003 | QA menyeluruh (API + UI + aturan) | aqua | **Selesai** | 04-qa.md |
| T-004 | Perbaiki bug Major/Minor QA | deco | **Selesai** | app/ |
| T-005 | Verifikasi ulang pasca-perbaikan | aqua | **Selesai (GO)** | verify-*.png |

## Keputusan
- 2026-11-06 — Orch menetapkan default Q-002/Q-004/Q-001/Q-003/Q-005/Q-008/R-01 (lihat `00-brief.md`).
- 2026-11-06 — Struktur data mengikuti 13 unit SKKNI / 61 indikator dari garis besar.
- 2026-11-06 — **QA GO**: Semua 5 bug terverifikasi, regresi 12 skenario lulus.

## Risiko tersisa (non-blokir MVP)
- Pemetaan teks 61 indikator ke unit SKKNI adalah usulan; harus diedit & diverifikasi asesor (Q-101).
- Kode unit belum dicocokkan dengan SKKNI resmi 2024/2025 (Q-102).
- Sertifikat IP Let's Encrypt bergantung dukungan klien ACME di VPS (Q-105).
- Tes Pengetahuan (teori) tidak masuk MVP (Q-103).
- Format sertifikat PDF belum ada (Q-104).
- Sinkron Google Sheets live belum diuji end-to-end (butuh kredensial).
- Restore backup terenkripsi belum diuji.
- Browser Safari/Firefox belum diuji.

## Artefak siap pakai
- **Aplikasi**: `app/` (FastAPI + SQLite WAL + SPA vanilla ES modules + PWA offline)
- **Jalankan**: `cd app && ./run.sh` → `http://localhost:8000/`
- **Setup awal**: buat akun asesor + simpan secret TOTP → login kode 6 digit
- **PRD**: `02-prd.md` v0.2 (400+ baris, aturan lengkap, 30+ AC)
- **Catatan build**: `03-build.md` (ringkasan, cara jalan, hasil tes, risiko)
- **QA report**: `04-qa.md` (9 skenario bisnis, 5 bug, GO)
- **Seed**: 13 unit SKKNI, 61 indikator, 5 sub kompetensi (2 usulan)

## Langkah selanjutnya (produksi)
1. Verifikasi Q-101 (teks indikator) & Q-102 (kode unit SKKNI) dengan asesor.
2. Setup VPS: Caddy (HTTPS IP cert) + systemd service + `backup.sh` cron.
3. Konfigurasi Google Sheets: service account + `GOOGLE_SHEETS_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON`.
4. Deploy & UAT asesor 1 hari sebelum UKK.