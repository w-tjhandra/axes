# PRD Lanjutan — Manajemen Ujian Tahunan, Arsip, Statistik, dan Sertifikat

**Versi:** 0.1  
**Status:** Draft untuk validasi pemilik produk  
**Tanggal:** 2026-11-15  
**Pemilik produk:** Welly  
**Dokumen induk:** [02-prd.md](./02-prd.md) v0.2 (MVP berjalan; tidak diganti)  
**Konteks aplikasi:** [app/README.md](./app/README.md), FastAPI + SQLite WAL + SPA PWA

---

## 1. Ringkasan

PRD ini memperluas aplikasi asesmen agar dapat digunakan berulang pada tahun
yang berbeda tanpa mencampur daftar peserta, hasil, dan arsip. Entitas baru
**Ujian** mewakili satu periode asesmen dengan tahun, judul, tanggal, sekolah
peserta, skema, dan status. Ujian dapat memiliki beberapa sekolah; di dalam
halaman Sekolah, peserta ditampilkan sebagai daftar induk sekolah dan dapat
dilihat berdasarkan judul ujian/tahun serta kelas atau kelompok ujiannya.

Ujian yang telah diarsipkan tetap dapat dicari, dibaca, dilaporkan, dan
diunduh, tetapi tidak dapat diubah. Dashboard menampilkan jumlah asesi serta
persentase kelulusan berdasarkan hasil asesmen yang sudah dikunci. Hasil
`kompeten_penuh`, `kompeten_sub`, dan `kompeten_unit` dihitung lulus; hasil
`belum_kompeten` dihitung tidak lulus.

Asesor dapat mengunggah template sertifikat DOCX ber-placeholder dan
menghasilkan PDF untuk asesi yang lulus. Sertifikat adalah dokumen internal
hasil asesmen; bukan sertifikat resmi LSP/BNSP kecuali kewenangan dan materi
resminya telah diverifikasi.

## 2. Kondisi saat ini dan masalah

MVP menghubungkan sekolah ke daftar peserta tetap dan asesmen terbaru peserta.
Belum ada objek periode ujian. Karena itu:

- Data tahun berjalan dan tahun berikutnya berisiko bercampur.
- Daftar peserta dan hasil sulit dilihat berdasarkan periode atau judul ujian.
- Tidak ada arsip ujian yang terpisah dan aman hanya-baca.
- Dashboard saat ini lebih berorientasi pada jumlah sekolah/skema dan ringkasan
  hasil, bukan statistik operasional per ujian.
- Belum ada pengelolaan template sertifikat dan penerbitan PDF terkontrol.

**Dampak:** pencarian dan rekap historis menjadi sulit, perubahan data peserta
dapat mengaburkan keadaan pada periode sebelumnya, dan pembuatan dokumen hasil
masih manual.

## 3. Tujuan dan bukan tujuan

### 3.1 Tujuan

1. Memisahkan setiap periode ujian menggunakan tahun dan judul ujian.
2. Memungkinkan sekolah dan kelompok kelas mengelola roster asesi per ujian
   tanpa menjadikan sekolah sebagai periode pelaksanaan.
3. Menyimpan riwayat pendaftaran dan hasil sehingga data tahun lama tetap utuh.
4. Menyediakan arsip ujian yang terpisah, hanya-baca, dan tetap dapat diekspor.
5. Menampilkan statistik jumlah asesi, cakupan asesmen, dan persentase lulus /
   tidak lulus yang definisinya jelas.
6. Menghasilkan sertifikat PDF dari template DOCX yang diunggah asesor.
7. Menghindari perubahan atau penghapusan data MVP saat migrasi ke model ujian.

### 3.2 Bukan tujuan

- Multi-user concurrent editing atau RBAC lengkap; aplikasi tetap single
  assessor untuk fase ini.
- Portal peserta untuk mengunduh sertifikat sendiri.
- Sertifikat digital dengan tanda tangan elektronik atau verifikasi publik.
- Membuat sertifikat resmi LSP/BNSP tanpa verifikasi aturan dan kewenangan.
- Editor desain dokumen di dalam aplikasi; template ditata di Word/LibreOffice.
- Mengubah formula kompetensi, ambang lulus, predikat, atau pemetaan instrumen
  yang ditentukan PRD MVP.
- Menghapus data historis atau menggabungkan hasil dari ujian berbeda ke satu
  hasil asesmen.

## 4. Pengguna dan kebutuhan

| Pengguna | Kebutuhan |
|---|---|
| Asesor/pemilik | Membuat ujian per tahun, mengatur sekolah dan kelompok, menilai, mengarsipkan, melihat statistik, mengelola template, dan menghasilkan sertifikat. |
| Koordinator sekolah (peran potensial) | Mengelola roster sekolah/ujian dan mengunduh rekap tanpa mengubah instrumen atau hasil. Belum termasuk akses multi-user pada fase ini. |
| Sistem | Menghubungkan peserta, ujian, skema, asesmen, hasil, ekspor, sertifikat, dan audit secara konsisten. |

## 5. Istilah dan model produk

- **Sekolah:** data induk institusi/TUK. Tidak mewakili satu tahun ujian.
- **Peserta:** data induk peserta milik sekolah. Data ini dapat dipakai pada
  beberapa ujian di tahun berbeda.
- **Ujian:** satu periode/peristiwa asesmen, memiliki **tahun + judul wajib**,
  tanggal opsional, satu atau lebih sekolah, serta satu atau lebih skema.
- **Kelompok ujian:** label kelompok/kelas pada keikutsertaan peserta di suatu
  ujian, misalnya `XII TKJ 1`, `Gelombang A`, atau `Sesi Pagi`. Kelompok ujian
  berbeda dari kolom kelas pada data induk peserta.
- **Keikutsertaan ujian (enrollment):** hubungan peserta dan ujian; menyimpan
  kelompok serta snapshot identitas yang digunakan pada periode tersebut.
- **Arsip ujian:** ujian berstatus arsip. Data hanya-baca dan tetap dapat
  ditinjau atau diekspor.
- **Asesmen final:** asesmen berstatus terkunci, memiliki hasil yang tersimpan.
- **Kelulusan untuk statistik:** hasil `kompeten_penuh`, `kompeten_sub`, atau
  `kompeten_unit`. `belum_kompeten` adalah tidak lulus.

### 5.1 Prinsip model

1. Satu ujian dapat melibatkan banyak sekolah; satu sekolah dapat mengikuti
   banyak ujian.
2. Satu ujian dapat melibatkan beberapa skema yang telah dipilih; setiap
   enrollment dan asesmen tetap terkait ke satu skema dan snapshot instrumen
   seperti pada MVP. Sekolah hanya dapat mendaftarkan peserta ke skema yang
   diaktifkan untuk ujian dan didukung oleh konfigurasi sekolah.
3. Seorang peserta dapat mengikuti banyak ujian, termasuk ujian tahunan
   berikutnya. Pendaftaran tahun baru tidak menimpa asesmen tahun lama.
4. Pada satu ujian, peserta didaftarkan satu kali per skema. Koreksi hasil
   memakai mekanisme buka-kunci dan audit yang sudah ada, bukan membuat upaya
   asesmen duplikat tanpa jejak.
5. Nama, nomor, kelas induk, dan kelompok yang ditampilkan pada laporan lama
   memakai snapshot pendaftaran, bukan nilai peserta yang mungkin diperbarui
   kemudian.
6. Sekolah dan skema tetap entitas terpisah dari ujian.

### 5.2 Model data konseptual

| Entitas | Atribut penting | Aturan |
|---|---|---|
| `exam` | `id`, `title`, `year`, `starts_on`, `ends_on`, `status`, waktu audit | Untuk ujian baru tahun dan judul wajib; pasangan judul+tahun unik. Record legacy sistem boleh tanpa tahun. Status: `draft`, `active`, `closed`, `archived`. |
| `exam_school` | `exam_id`, `school_id` | Relasi sekolah yang berpartisipasi; unik per pasangan. |
| `exam_scheme` | `exam_id`, `scheme_kode` | Skema yang tersedia untuk ujian; unik per pasangan. |
| `exam_enrollment` | `exam_id`, `participant_id`, `scheme_kode`, `group_label`, snapshot nomor/nama/kelas, status | Unik per ujian+peserta+skema; sekolah peserta harus terdaftar pada ujian. Status minimal `enrolled` dan `withdrawn`. |
| `assessment` (perluasan) | relasi ke `exam_enrollment_id` opsional untuk data legacy | Asesmen baru wajib berada dalam konteks ujian; asesmen lama dipertahankan dan ditandai legacy. |
| `certificate_template` | skema/ujian, versi, nama file, checksum, lokasi privat, waktu upload, status aktif | Versi lama tetap tercatat; file tidak disajikan dari direktori publik. |
| `certificate_issue` | enrollment/assessment, template version, nomor sertifikat, file PDF, checksum, waktu terbit, status | Terbit maksimal satu sertifikat aktif per enrollment+assessment+template; penerbitan ulang diaudit dan file lama tidak diam-diam ditimpa. |

**Catatan desain:** `exam_enrollment` perlu membawa `scheme_kode` supaya satu
peserta dapat mengikuti beberapa skema pada periode yang sama. Snapshot
identitas membuat laporan dan sertifikat historis stabil. Detail tipe data,
indeks, dan strategi penomoran sertifikat ditetapkan pada desain teknis setelah
PRD disetujui.

## 6. Alur utama

### 6.1 Membuat dan mengatur Ujian

1. Asesor membuka menu **Ujian** dan membuat ujian dengan judul dan tahun.
2. Asesor dapat mengisi tanggal mulai/selesai, memilih skema, dan
   menambahkan satu atau lebih sekolah.
3. Dari sekolah yang ikut serta, asesor menambahkan peserta yang telah ada atau
   mengimpor daftar peserta. Asesor memilih kelompok ujian; nilai default dapat
   mengikuti kelas induk peserta tetapi harus dapat diedit untuk ujian itu.
4. Asesor memeriksa duplikasi roster dan ringkasan sebelum mengaktifkan ujian.
5. Pengaktifan mengizinkan pendaftaran dan pembuatan asesmen sesuai skema
   ujian.

### 6.2 Menu Sekolah

- Daftar sekolah tetap menjadi pintu masuk berdasarkan institusi.
- Detail sekolah memiliki filter/pemilih ujian, default ke ujian aktif terbaru.
- Daftar peserta dapat dikelompokkan atau difilter berdasarkan judul dan tahun
  ujian, kelompok ujian, status pendaftaran, status asesmen, dan skema.
- Tersedia tampilan **Semua peserta sekolah** untuk daftar induk; tampilan ini
  dibedakan secara visual dari **Roster ujian** agar peserta yang belum
  terdaftar pada ujian tidak dianggap sebagai asesi ujian.
- Aksi menambah peserta ke ujian tidak membuat duplikat peserta induk bila
  nomor peserta yang sama sudah ada dalam sekolah tersebut.

### 6.3 Menilai, menutup, dan mengarsipkan

- Asesmen selalu dibuat dari keikutsertaan peserta pada ujian dan skema.
- Aturan skor, simpan offline, lock/unlock, dan kalkulasi hasil mengikuti PRD
  MVP.
- `draft`: konfigurasi dan roster dapat diedit; asesmen belum dapat dimulai.
- `active`: roster dapat dikelola dan asesmen dapat dimulai/dilanjutkan.
- `closed`: roster tidak dapat ditambah; asesmen yang belum selesai dapat
  diselesaikan oleh asesor sesuai aturan penutupan yang ditetapkan.
- `archived`: semua data ujian dan hasil menjadi hanya-baca; dapat dilihat,
  dicari, dan diekspor.
- Arsip tidak menghapus peserta, skor, audit, atau sertifikat. Data lama tidak
  dapat diubah melalui UI maupun API.
- Pengarsipan ditolak bila masih ada asesmen `in_progress`. Asesor harus
  menyelesaikan semua asesmen berjalan; pendaftaran tanpa asesmen boleh
  dikeluarkan (withdrawn) dengan audit. Tidak ada force-archive diam-diam.
- Pendaftaran tanpa asesmen dapat ditandai `withdrawn` dengan audit. Pendaftaran
  yang sudah memiliki asesmen berjalan tidak boleh dihapus atau dikeluarkan
  untuk mengakali pemeriksaan arsip; asesmennya harus diselesaikan lebih dulu.
- Buka kembali ujian arsip bukan aksi biasa; jika diperlukan pada fase mendatang,
  wajib alasan, konfirmasi eksplisit, dan audit.

### 6.4 Statistik dashboard

Dashboard memiliki filter ujian (judul+tahun), sekolah, dan skema. Default
menampilkan ujian aktif terbaru; tersedia pilihan semua ujian untuk analisis
lintas periode.

Definisi hitungan untuk ujian terpilih:

- **Total asesi:** jumlah enrollment berstatus `enrolled` (tidak termasuk
  `withdrawn`).
- **Sudah dinilai:** enrollment dengan hasil asesmen terkunci.
- **Belum selesai:** enrolled tanpa hasil final terkunci (dibedakan menjadi
  belum mulai dan sedang dinilai).
- **Lulus:** hasil final terkunci dengan outcome `kompeten_penuh`,
  `kompeten_sub`, atau `kompeten_unit`.
- **Tidak lulus:** hasil final terkunci dengan outcome `belum_kompeten`.
- **Persentase lulus:** `jumlah lulus / jumlah hasil final terkunci × 100`.
- **Persentase tidak lulus:** `jumlah tidak lulus / jumlah hasil final
  terkunci × 100`.
- Enrollment yang belum memiliki hasil final tidak masuk denominator kedua
  persentase. Tampilkan jumlah dan cakupan penyelesaian agar persentase tidak
  terlihat lebih baik hanya karena banyak peserta belum dinilai.
- Tampilkan persentase dan jumlah mentah (`lulus 8/10 · 80%`) serta label
  denominator. Bila belum ada hasil final, tampilkan `Belum ada hasil final`,
  bukan `0% lulus`.
- Tampilkan empat outcome detail pada rekap; agregasi lulus/tidak lulus hanya
  untuk ringkasan dashboard.

### 6.5 Template dan penerbitan sertifikat

1. Asesor mengunggah DOCX template untuk skema atau memilih template khusus
   ujian. Template khusus ujian mengalahkan template default skema. Template
   berisi placeholder yang didukung sistem.
2. Sistem memeriksa tipe/ukuran file, membaca placeholder, dan menunjukkan
   placeholder yang tersedia, wajib, tidak dikenal, atau belum terisi.
3. Asesor mengaktifkan versi template setelah preview contoh berhasil.
4. Tombol **Generate Sertifikat** tersedia untuk hasil terkunci yang lulus.
5. Hasil generate PDF ditautkan pada peserta, ujian, skema, hasil, dan versi
   template. Asesor dapat mengunduh PDF individual.
6. Aksi **Generate massal** untuk seluruh peserta lulus dan unduh ZIP disarankan
   sebagai kebutuhan SHOULD; satu file gagal tidak membatalkan semua file.
7. Penerbitan ulang menghasilkan nomor/versi penerbitan baru dan audit;
   dokumen yang sudah terbit tidak berubah saat template atau data peserta
   diperbarui.
8. Peserta tidak lulus atau asesmen belum dikunci tidak dapat menerima
   sertifikat kompetensi. Mereka tetap dapat masuk rekap hasil.

## 7. Placeholder sertifikat

Placeholder standar yang disarankan:

| Placeholder | Sumber |
|---|---|
| `{{participant_name}}` | Snapshot nama pada pendaftaran ujian |
| `{{participant_number}}` | Snapshot nomor peserta |
| `{{participant_class}}` | Snapshot kelas/kelompok ujian |
| `{{school_name}}` | Nama sekolah pada konteks ujian |
| `{{exam_title}}` | Judul ujian |
| `{{exam_year}}` | Tahun ujian |
| `{{exam_date}}` | Tanggal ujian atau rentang tanggal |
| `{{scheme_name}}` | Nama skema pada hasil asesmen |
| `{{outcome_label}}` | Label outcome dari hasil yang terkunci |
| `{{predicate}}` | Predikat asesmen jika hasil menyediakannya |
| `{{certificate_number}}` | Nomor unik sertifikat |
| `{{issued_date}}` | Tanggal penerbitan PDF |

Template yang tidak memiliki placeholder wajib harus ditolak dengan pesan
spesifik; tidak boleh menghasilkan dokumen sukses yang sebagian datanya kosong.
Placeholder opsional yang tidak digunakan boleh diabaikan. Wording dan desain
sertifikat tetap menjadi tanggung jawab pemilik produk/asesor.

Placeholder wajib yang disarankan: `participant_name`, `participant_number`,
`school_name`, `exam_title`, `exam_year`, `scheme_name`, `outcome_label`,
`certificate_number`, dan `issued_date`. `participant_class`, `exam_date`, dan
`predicate` opsional.

## 8. Functional requirements

| ID | Prioritas | Requirement | Acceptance criteria |
|---|---|---|---|
| EX-001 | MUST | Buat, lihat, dan ubah ujian dengan tahun, judul, tanggal opsional, status, dan catatan. | Judul/tahun wajib; tanggal selesai tidak lebih awal dari tanggal mulai; judul+tahun duplikat ditolak dengan pesan jelas. |
| EX-002 | MUST | Ujian mendukung banyak sekolah dan satu atau lebih skema. | Hanya sekolah/skema yang terasosiasi dapat dipilih untuk roster/asesmen; perubahan skema tidak mengubah snapshot instrumen lama. |
| EX-003 | MUST | Menu Ujian menampilkan daftar dengan filter tahun, judul, status, skema, dan sekolah. | Pencarian/filter dapat dipakai bersama; total hasil cocok dengan pagination. |
| EX-004 | MUST | Roster peserta per ujian memuat kelompok ujian dan snapshot identitas. | Peserta sama boleh didaftarkan pada ujian tahun berbeda; peserta+ujian+skema yang sama tidak dapat diduplikasi. |
| EX-005 | MUST | Tambah peserta dari daftar induk sekolah atau impor CSV ke roster ujian. | Duplikat dilaporkan per baris; data roster tidak menimpa data ujian terdahulu. |
| EX-006 | MUST | Halaman Sekolah menampilkan daftar induk dan roster per ujian sebagai tampilan terpisah. | Pemilih ujian menampilkan judul+tahun; filter kelompok dan status bekerja tanpa mencampur peserta dari periode lain. |
| EX-007 | MUST | Asesmen baru terikat ke enrollment ujian dan skema yang dipilih. | Asesmen tidak dapat dibuat tanpa konteks ujian aktif; satu enrollment tidak menghasilkan asesmen ganda pada skema yang sama. |
| EX-008 | MUST | Ujian mempunyai lifecycle `draft`, `active`, `closed`, `archived`. | Transisi status tervalidasi; ujian archived tidak bisa diubah melalui UI maupun API; setiap transisi dicatat pada audit. |
| EX-009 | MUST | Sediakan menu Arsip Ujian terpisah. | Daftar arsip dapat dicari/filter; detail, hasil, audit relevan, ekspor, dan PDF terbit tetap dapat dilihat/diunduh. |
| EX-010 | MUST | Ujian tidak dapat diarsipkan bila memiliki asesmen belum final. | API mengembalikan konflik dan identitas/count asesmen yang belum selesai; tidak ada perubahan parsial. |
| EX-011 | MUST | Dashboard menampilkan total asesi, sudah dinilai, belum mulai, sedang dinilai, lulus, tidak lulus, dan cakupan penyelesaian. | Setiap angka mengikuti definisi denominator di §6.4 dan dapat difilter ujian/sekolah/skema. |
| EX-012 | MUST | Dashboard menampilkan persentase lulus dan tidak lulus berdasarkan hasil terkunci. | Persentase lulus+tidak lulus = 100% pada denominator final (toleransi pembulatan ±1 poin); tanpa hasil final tampil status kosong, bukan nilai palsu. |
| EX-013 | MUST | Upload dan versioning template DOCX per skema atau ujian. | Terima DOCX sampai batas rekomendasi 10 MiB; checksum, versi, uploader, waktu upload dan status tersimpan; file lama tetap dapat ditelusuri. |
| EX-014 | MUST | Validasi placeholder wajib dan uji preview sebelum aktivasi. | Placeholder wajib hilang/unknown dilaporkan; template invalid tidak dapat diaktifkan atau dipakai generate. |
| EX-015 | MUST | Generate PDF individual untuk peserta dengan hasil terkunci yang lulus. | Data sertifikat berasal dari snapshot enrollment dan hasil terkunci; PDF dapat dibuka dan metadata penerbitan tercatat. |
| EX-016 | MUST | Nomor sertifikat unik dan tidak berubah setelah terbit. | Dua request bersamaan tidak menghasilkan nomor ganda; generate ulang tercatat sebagai penerbitan baru/versi baru. |
| EX-017 | SHOULD | Generate massal untuk hasil lulus dalam ujian/skema terpilih. | File berhasil dikemas ke ZIP; kegagalan per peserta ditampilkan dalam laporan dan tidak menghilangkan dokumen lain. |
| EX-018 | MUST | Ekspor roster dan hasil per ujian ke CSV/XLSX. | Ekspor memuat judul/tahun, sekolah, kelompok, skema, status hasil, outcome detail, dan timestamp; data tidak lintas ujian. |
| EX-019 | MUST | Audit perubahan roster, transisi status, template, generate, unduh, dan penerbitan ulang. | Audit memuat waktu, aktor, objek, action dan metadata yang relevan; tidak menyimpan password atau TOTP. |
| EX-020 | MUST | Mewariskan kemampuan offline penilaian tanpa membuat operasi offline terhadap arsip. | Perubahan skor offline tetap idempoten; client lama tidak dapat mengubah exam yang sudah diarsipkan setelah tersambung kembali. |

## 9. Kebutuhan nonfungsional

### 9.1 Keamanan dan privasi

- Semua endpoint exam/roster/sertifikat memakai autentikasi sesi dan CSRF yang
  sama dengan aplikasi.
- Template dan PDF disimpan di luar direktori publik, hanya diunduh melalui
  endpoint terautentikasi, dan tidak dieksekusi sebagai konten aktif.
- Validasi konten file berdasarkan ekstensi, MIME, magic bytes, batas ukuran,
  nama file aman, serta batas waktu dan resource konversi.
- DOCX mengandung konten tidak tepercaya; konversi berjalan tanpa macro,
  eksternal network access, atau akses ke file sensitif server.
- Tautan download tidak memakai path filesystem dari input pengguna.
- Audit menyimpan hash dan metadata file, bukan salinan data sensitif yang tidak
  perlu.
- Kebijakan retensi, akses data pendidikan, dan izin penggunaan nama/foto pada
  sertifikat ditinjau sebelum produksi.

### 9.2 Kinerja, reliabilitas, dan aksesibilitas

- Dashboard untuk ujian hingga 5.000 enrollment dapat dimuat ≤2 detik pada
  lingkungan target dengan indeks dan agregasi SQL yang sesuai.
- Pencarian daftar peserta memakai pagination; UI tidak memuat seluruh data
  historis sekaligus.
- PDF generation mempunyai status `queued`, `processing`, `ready`, atau
  `failed`; error konverter eksplisit dan bisa dicoba ulang.
- Jika converter DOCX→PDF tidak tersedia, fitur generate dinyatakan tidak siap
  dan menampilkan instruksi konfigurasi; tidak membuat file PDF kosong.
- Alur roster, dashboard, dan sertifikat dapat digunakan pada viewport ponsel,
  keyboard, dan pembaca layar dasar.
- Tanggal disimpan dalam format konsisten; tahun yang digunakan untuk
  statistik berasal dari ujian, bukan timezone perangkat.

## 10. API yang direncanakan

Nama endpoint berikut adalah rancangan kebutuhan, bukan kontrak implementasi
final. Respons mengikuti pola JSON `data`/`meta` aplikasi yang ada.

| Method dan path | Tujuan |
|---|---|
| `GET/POST /api/exams` | Daftar/filter dan membuat ujian. |
| `GET/PATCH /api/exams/{exam_id}` | Detail atau ubah ujian sesuai status. |
| `POST /api/exams/{exam_id}/schools` | Hubungkan sekolah ke ujian. |
| `POST /api/exams/{exam_id}/schemes` | Hubungkan skema ke ujian. |
| `GET/POST /api/exams/{exam_id}/enrollments` | Roster, pendaftaran, dan filter kelompok. |
| `POST /api/exams/{exam_id}/enrollments/import` | Impor roster dengan validasi dan laporan per baris. |
| `GET /api/exams/{exam_id}/summary` | Statistik asesi, progres, lulus, dan tidak lulus. |
| `POST /api/exams/{exam_id}/close` | Tutup pendaftaran ujian. |
| `POST /api/exams/{exam_id}/archive` | Arsipkan dengan validasi state dan audit. |
| `GET /api/archives/exams` | Daftar arsip ujian. |
| `GET /api/schools/{school_id}/participants?exam_id=...` | Daftar peserta sekolah/roster ujian terpilih. |
| `GET/POST /api/certificate-templates` | Kelola template, scope skema/ujian, dan versinya. |
| `POST /api/certificates/preview` | Validasi dan preview sample hasil template. |
| `POST /api/enrollments/{enrollment_id}/certificate` | Buat sertifikat PDF individual. |
| `POST /api/exams/{exam_id}/certificates/bulk` | (SHOULD) antrean sertifikat massal. |
| `GET /api/certificates/{certificate_id}/download` | Unduh PDF terautentikasi. |

Semua endpoint yang mengubah state memerlukan CSRF, memvalidasi status exam, dan
menghasilkan audit record. Filter skema dan ujian harus konsisten pada sekolah,
rekap, dashboard, dan ekspor.

## 11. Acceptance criteria end-to-end

1. Asesor dapat membuat ujian `UKK JNT 2027` dan `UKK JNT 2028` tanpa data
   peserta atau hasil kedua ujian bercampur.
2. Satu sekolah dapat berpartisipasi pada dua ujian; peserta lama dapat
   didaftarkan ulang tanpa membuat master peserta ganda.
3. Peserta kelas induk berubah setelah UKK 2027; laporan dan sertifikat 2027
   tetap menampilkan snapshot identitas saat didaftarkan.
4. Di halaman sekolah, memilih ujian 2027 hanya menampilkan roster 2027;
   memilih 2028 menampilkan roster 2028.
5. Peserta yang ikut dua skema pada satu ujian memiliki enrollment/asesmen
   terpisah per skema dengan hasil masing-masing.
6. Hasil terkunci `kompeten_sub` dan `kompeten_unit` dihitung sebagai lulus;
   `belum_kompeten` dihitung tidak lulus.
7. Enrollment tanpa hasil final dihitung dalam total asesi tetapi tidak masuk
   denominator persentase lulus/tidak lulus.
8. Pada 8 hasil lulus dan 2 tidak lulus dari 10 hasil final, dashboard
   menampilkan lulus `8/10 · 80%`, tidak lulus `2/10 · 20%`, dan cakupan sesuai
   jumlah roster.
9. Jika belum ada hasil final, dashboard tidak menunjukkan `0% lulus` seolah
   hasil telah dinilai.
10. Ujian arsip muncul di menu Arsip dan detailnya dapat diekspor; update skor,
    roster, tanggal, template, atau status ditolak oleh API.
11. Pengarsipan ujian dengan asesmen `in_progress` ditolak tanpa mengubah
    status ujian atau asesmen.
12. Mengunggah template non-DOCX atau DOCX di atas batas ukuran ditolak dengan
    pesan format/ukuran yang spesifik (batas awal rekomendasi 10 MiB).
13. Template yang kehilangan placeholder wajib tidak dapat diaktifkan dan
    preview menjelaskan placeholder yang hilang.
14. PDF untuk peserta lulus memuat identitas snapshot, sekolah, judul/tahun
    ujian, skema, outcome, tanggal, dan nomor sertifikat yang benar.
15. Peserta gagal, belum dinilai, atau asesmennya belum terkunci tidak
    mendapatkan aksi generate sertifikat kompetensi.
16. Konverter yang mati/gagal menampilkan status failed dan instruksi; tidak
    menghasilkan sertifikat kosong atau status sukses semu.
17. Generate ulang dan permintaan bersamaan tidak menimpa diam-diam file lama
    dan tidak menggandakan nomor sertifikat.
18. Ekspor sekolah dan ujian menghasilkan hanya data dari filter yang dipilih
    dan tetap memuat kategori outcome asli.
19. Data ujian arsip tetap tersedia setelah service-worker cache diperbarui,
    aplikasi di-restart, dan backup dipulihkan.
20. Uji mobile mencakup tambah roster, filter ujian, melihat ringkasan, dan
    mengunduh sertifikat.

## 12. Migrasi data MVP

- Migrasi bersifat additive; tabel sekolah, peserta, skor, asesmen, audit, dan
  snapshot instrumen lama tidak dihapus atau ditulis ulang.
- Asesmen yang sudah ada tidak boleh ditebak sebagai milik ujian baru.
  Pertahankan dalam kelompok **Data lama / legacy** di arsip khusus (record
  sistem legacy boleh memiliki tahun kosong), dan jangan masukkan ke statistik
  ujian aktif.
- Jika tahun dapat diambil secara deterministik dari timestamp asesmen, tahun
  dapat dicatat sebagai metadata legacy dengan penanda sumber; jangan
  mengarang judul ujian/sekolah/grup.
- Data legacy tetap dapat dibaca dan diekspor dengan perilaku hasil lama.
- Peserta yang belum memiliki asesmen tetap menjadi daftar induk sekolah dan
  tidak otomatis dianggap terdaftar pada ujian baru.
- Migration dijalankan dalam transaksi, aman dijalankan ulang, membuat backup
  sebelum perubahan, dan menyediakan laporan jumlah baris sebelum/sesudah.
- Uji migrasi terhadap salinan database nyata dan uji restore sebelum rilis.

## 13. Metrik sukses

| Metrik | Target | Cara ukur |
|---|---:|---|
| Kebocoran lintas periode | 0 baris hasil ujian A tampil pada ujian B | Tes API/UI dengan sekolah dan peserta yang sama di dua ujian. |
| Akurasi statistik | 100% sama dengan hitung independen dari hasil final | Tes kombinasi tiap outcome, withdrawn, belum mulai, in-progress, dan filter. |
| Keutuhan arsip | 0 perubahan data melalui UI/API pada ujian archived | Tes mutasi langsung dan regresi offline queue. |
| Akurasi snapshot | 100% identitas historis stabil setelah master peserta diubah | Tes edit nama/kelas setelah enrollment. |
| Sertifikat berhasil | ≥99% untuk template valid dan converter sehat | Job PDF test; kegagalan ditampilkan dan dapat ditindak. |
| Waktu dashboard | ≤2 detik untuk 5.000 enrollment | Pengukuran lingkungan target setelah query terindeks. |
| Keberhasilan operasional | Asesor dapat membuat ujian dan mendaftarkan satu rombongan tanpa panduan teknis | UAT dengan data uji dan alur sekolah yang representatif. |

## 14. Risiko dan rekomendasi

| Prioritas | Risiko/rekomendasi | Tindakan |
|---|---|---|
| P0 — validitas | Indikator dan kode unit belum seluruhnya diverifikasi terhadap SKKNI resmi. | Selesaikan validasi asesor/SKKNI sebelum ujian produksi; catat versi instrumen yang disetujui. |
| P0 — data historis | Relasi asesmen saat ini berbasis peserta dan mengembalikan asesmen terbaru; tanpa perubahan model dapat mencampur tahun. | Tambahkan exam enrollment sebagai konteks asesmen dan pertahankan snapshot; migrasikan secara additive. |
| P0 — arsip | UI-only read-only tidak cukup karena endpoint dan offline queue masih dapat mengubah nilai. | Enforcement status archived di backend, transaksi mutasi, dan penolakan sinkron skor lama. |
| P1 — sertifikat | DOCX→PDF memerlukan converter operasional dan hasil dapat berbeda antar versi. | Tetapkan LibreOffice headless atau converter terisolasi, kunci versi, tambahkan health check, fixture template, dan tes visual PDF. |
| P1 — privasi | Sertifikat berisi data identitas peserta. | Unduh terautentikasi, penyimpanan privat, retention policy, audit akses, dan persetujuan wording. |
| P1 — backup | Template dan PDF baru harus ikut backup dan restore, bukan hanya database. | Backup konsisten untuk DB + storage dokumen; lakukan restore drill lengkap. |
| P1 — sinkronisasi | Google Sheets per sekolah mungkin mencampur tahun bila kunci idempotensi masih peserta/sekolah saja. | Sertakan exam ID/tahun dalam key dan kolom ekspor; uji live dengan akun layanan sebelum produksi. |
| P2 — penggunaan | Dashboard lintas tahun dapat menyesatkan bila denominator atau ujian default tidak jelas. | Default ke ujian aktif terbaru, tampilkan filter terpilih, hitungan mentah, denominator, dan coverage. |
| P2 — kualitas | Tabel dan aksi sertifikat rawan overflow mobile. | UAT viewport 390px dan keyboard/screen-reader dasar untuk setiap rilis. |

### 14.1 Saran tambahan produk

1. Gunakan filter dashboard dengan **ujian aktif terbaru sebagai default**;
   jangan gabungkan seluruh tahun secara default.
2. Tampilkan angka absolut berdampingan dengan persentase dan cakupan final.
3. Pertahankan empat outcome detail pada laporan; agregasi lulus/tidak lulus
   hanya dipakai untuk ringkasan.
4. Simpan snapshot identitas peserta pada enrollment; ini penting untuk
   konsistensi dokumen tahun lalu.
5. Sediakan preview template dengan satu peserta contoh sebelum template
   diaktifkan.
6. Jadikan sertifikat massal ZIP sebagai SHOULD setelah PDF individual stabil.
7. Siapkan contoh DOCX template yang sudah memiliki placeholder dan spesifikasi
   ukuran kertas/logo agar asesor hanya perlu mengunggah template.
8. Tampilkan catatan bahwa sertifikat bersifat internal sampai isi, tanda
   tangan, dan otoritas penerbit telah disetujui.

## 15. Rencana implementasi yang disarankan

### Tahap 0 — Keputusan dan kesiapan

- Validasi terminologi judul ujian, kelompok, tanggal, pembatalan peserta, dan
  kebijakan penerbitan sertifikat.
- Verifikasi instrumen/kode SKKNI dengan asesor.
- Putuskan converter DOCX→PDF dan lokasi penyimpanan aman.
- Siapkan fixture template DOCX dan contoh data ujian dua tahun.

### Tahap 1 — Ujian dan roster

- Migrasi additive `exam`, asosiasi sekolah/skema, dan enrollment dengan
  snapshot.
- Menu Ujian, create/edit, status lifecycle, roster manual/CSV dan kelompok.
- Hubungkan asesmen baru ke enrollment; pertahankan akses data legacy.
- Filter peserta berdasarkan ujian di detail sekolah.
- Uji tidak ada kebocoran lintas sekolah/periode/skema.

### Tahap 2 — Arsip dan dashboard

- Implementasi enforcement archive di backend, audit transisi, dan menu Arsip.
- Statistik dashboard dengan filter ujian/sekolah/skema dan denominator yang
  disetujui.
- Ekspor roster/hasil per ujian dan uji Sheets dengan kunci idempotensi baru.
- UAT mobile dan uji restore database + lampiran.

### Tahap 3 — Template dan sertifikat

- Upload/versioning/validasi template dan preview.
- Job PDF generation terisolasi, status yang dapat diamati, download individual.
- Batch ZIP setelah alur individual dan converter lulus QA.
- Verifikasi template visual, nomor sertifikat, audit penerbitan ulang, dan
  prosedur restore arsip.

## 16. Pertanyaan tersisa sebelum implementasi

Keputusan berikut belum menghalangi penulisan PRD, tetapi harus dipastikan
sebelum kode Tahap 1–3:

1. Apakah tanggal ujian berupa tanggal mulai/selesai atau tanggal per sesi?
2. Apakah peserta boleh withdrawn/dibatalkan setelah asesmen dimulai, dan
   bagaimana hasil parsial ditampilkan?
3. Apakah nomor sertifikat mengikuti format tertentu, prefix sekolah/skema,
   atau nomor urut tahunan?
4. Apakah logo, tanda tangan/stempel, dan foto peserta sudah ada dalam template,
   atau perlu field upload terpisah?
5. Apakah sertifikat boleh diterbitkan untuk `kompeten_unit` dan
   `kompeten_sub`, atau hanya `kompeten_penuh`? Default PRD saat ini mengikuti
   definisi statistik lulus yang disetujui dan mengizinkan seluruh outcome
   kompeten.
6. Berapa lama file template dan PDF sertifikat harus disimpan?
7. Apakah koordinator sekolah akan membutuhkan akun sendiri pada fase ini?
8. Apakah batas upload rekomendasi 10 MiB sesuai, atau perlu dinaikkan untuk
   template beresolusi tinggi?

## 17. Changelog

- **v0.1 (2026-11-15):** PRD lanjutan awal untuk ujian tahunan, roster sekolah,
  arsip, statistik dashboard, template DOCX, dan sertifikat PDF.
