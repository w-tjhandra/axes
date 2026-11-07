# Brief & Keputusan — Platform Penilaian UKK Junior Network Technician

Status: eksekusi
Tanggal: 2026-11-06
Pemilik produk: Welly (asesor, satu-satunya pengguna)

## Sumber kebenaran

1. **Garis besar PRD dari pengguna** (pesan 2026-11-06) — 13 unit SKKNI, 61 indikator, 5 sub kompetensi.
2. Instrumen pendukung di `~/Downloads/` (teks indikator, aturan pendukung).
3. **Bukan** struktur 49 item pada `Master Data ... .xlsx` — itu instrumen Jotform lama, hanya acuan historis.

## Keputusan atas pertanyaan blokir

| ID | Keputusan | Alasan |
|---|---|---|
| Q-002 | Indikator "tidak dikerjakan" = skor **0**, denominator tetap penuh | Sesuai garis besar 5.1; konsisten dengan instrumen |
| Q-004 | MVP **tidak** menegakkan dependensi antar-indikator; hanya peringatan lunak. Matriks lengkap ditunda | Tidak ada sumber matriks; jangan mengarang aturan |
| Q-001 | Bobot indikator **sama** (1), skor 0–3; dapat diubah di Config | Sesuai rumus garis besar 5.1 |
| Q-003 | Ambang lulus unit **70%**, dibandingkan sebagai bilangan bulat `skor × 10 ≥ 21 × jumlah_indikator` | Garis besar 5.1 |
| Q-005 | Bukti foto **tidak** masuk MVP; catatan teks per unit/asesmen tetap ada. Foto masuk Tahap 2 | Menghindari risiko kuota & mempercepat MVP |
| Q-008 | Auth sinkron Sheets: **static bearer API key** untuk worker internal; login pengguna = sesi + TOTP | Sederhana, satu pengguna, cukup aman di VPS |
| Q-012 | Tidak berlaku pada struktur 13 unit; dokumentasi/report sheet masuk unit 022 | Struktur outline |
| R-01 | Tidak ada foto di MVP → kuota IndexedDB bukan risiko MVP | Ditunda bersama Q-005 |

## Keputusan arsitektur

- **Backend sumber kebenaran:** FastAPI + SQLite (WAL) di VPS.
- **Frontend:** SPA responsif (vanilla ES modules, tanpa build step), service worker + IndexedDB sebagai antrean offline.
- **Sinkron:** skor dikirim idempoten (`assessment_id + indicator_id`), last-write-wins (satu pengguna).
- **Google Sheets:** satu arah lewat outbox worker + service account; tab per sekolah; idempoten per (sekolah, nomor peserta). Jika kredensial belum ada, worker berstatus `disabled` dan outbox tetap tersimpan.
- **Auth:** password hash (PBKDF2/argon2) + TOTP; cookie sesi HttpOnly, Secure (dapat dimatikan untuk dev), SameSite=Strict; rate limit login.
- **Backup:** `sqlite3 .backup` harian + enkripsi opsional; skrip + contoh cron.
- **TLS:** contoh Caddy untuk IP cert / self-signed; aplikasi tidak mengurus ACME sendiri.

## Desain UI

- Referensi: AeroPanel (codervent). Palet: primary `#4f46e5`, success `#22c55e`, danger `#ef4444`, warning `#f59e0b`, info `#06b6d4`, border `#e5e7eb`, surface `#ffffff`, page `#f6f7f9`, text `#111827`, muted `#6b7280`.
- Font: **Space Grotesk** (Google Fonts), fallback system sans.
- Minimalis: tanpa gradien, tanpa glassmorphism, tanpa emoji, tanpa hero besar. Sidebar 260px, topbar 64px, card radius 12px, shadow halus, spacing 8px.
- Tombol skor 0–3 target sentuh ≥ 44px; bar nilai dengan penanda 70%; mode terang/gelap.
