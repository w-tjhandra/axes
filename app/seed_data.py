"""Seed multi-skema asesmen: JNT-SMK (13 unit, 61 indikator), LSA-PRO, dan CNA-MTC.

Penjelasan Teknis (1-2 kalimat): Modul ini menginisialisasi data referensi multi-skema secara
idempoten (menggunakan `INSERT OR IGNORE`), mirip seperti konfigurasi bootstrap awal pada router
sehingga skema bawaan selalu tersedia tanpa menimpa kustomisasi yang sudah dibuat asesor.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

DEFAULT_SCHEME_KODE = "JNT-SMK"

SCHEMES: list[dict[str, Any]] = [
    {
        "kode": "JNT-SMK",
        "nama": "Junior Network Technician",
        "kategori": "UKK SMK / Vokasi",
        "deskripsi": "Skema Uji Kompetensi Keahlian (UKK) Teknik Komputer & Jaringan berbasis 13 Unit SKKNI, 61 Indikator, dan 5 Sub Kompetensi.",
        "pass_threshold": 70,
        "predicate_sangat_mahir": 90,
        "predicate_mahir": 80,
        "predicate_cakap": 70,
        "templates": {
            "penuh": (
                "Peserta {peserta} dinyatakan kompeten sebagai Junior Network "
                "Technician dengan predikat {predikat}."
            ),
            "sub": (
                "Peserta {peserta} dinyatakan kompeten pada sub kompetensi {sub} "
                "dengan predikat {predikat}."
            ),
            "unit": (
                "Peserta {peserta} dinyatakan kompeten pada unit {unit} dengan "
                "predikat {predikat}."
            ),
            "belum": "Peserta {peserta} dinyatakan belum kompeten.",
        },
    },
    {
        "kode": "LSA-PRO",
        "nama": "Linux System & Server Administrator",
        "kategori": "Sertifikasi Industri / PT Axelbit",
        "deskripsi": "Skema asesmen administrasi server Linux mencakup manajemen storage LVM, hardening SSH/Firewall, layanan web/reverse proxy, dan automasi Bash backup.",
        "pass_threshold": 70,
        "predicate_sangat_mahir": 90,
        "predicate_mahir": 80,
        "predicate_cakap": 70,
        "templates": {
            "penuh": (
                "Peserta {peserta} dinyatakan kompeten sebagai Linux System & Server "
                "Administrator dengan predikat {predikat}."
            ),
            "sub": (
                "Peserta {peserta} dinyatakan kompeten pada sub kompetensi {sub} "
                "dengan predikat {predikat}."
            ),
            "unit": (
                "Peserta {peserta} dinyatakan kompeten pada unit {unit} dengan "
                "predikat {predikat}."
            ),
            "belum": "Peserta {peserta} dinyatakan belum kompeten.",
        },
    },
    {
        "kode": "CNA-MTC",
        "nama": "Enterprise Routing & Switching Associate",
        "kategori": "Pelatihan Infrastruktur / Jaringan",
        "deskripsi": "Skema asesmen engineer jaringan mencakup routing dinamis OSPF, redundansi VLAN/STP, VPN IPSec site-to-site, serta monitoring trafik SNMP.",
        "pass_threshold": 70,
        "predicate_sangat_mahir": 90,
        "predicate_mahir": 80,
        "predicate_cakap": 70,
        "templates": {
            "penuh": (
                "Peserta {peserta} dinyatakan kompeten sebagai Enterprise Routing & "
                "Switching Associate dengan predikat {predikat}."
            ),
            "sub": (
                "Peserta {peserta} dinyatakan kompeten pada sub kompetensi {sub} "
                "dengan predikat {predikat}."
            ),
            "unit": (
                "Peserta {peserta} dinyatakan kompeten pada unit {unit} dengan "
                "predikat {predikat}."
            ),
            "belum": "Peserta {peserta} dinyatakan belum kompeten.",
        },
    },
]

# (kode unit, judul, daftar teks indikator, indeks teks usulan) untuk JNT-SMK
UNITS: list[tuple[str, str, list[str], set[int]]] = [
    (
        "J.611000.003.02",
        "Merancang Topologi Jaringan",
        [
            "Sketsa topologi lengkap dan sesuai desain konsultan (ISP - Router - Switch - AP/Client).",
            "Switch Port Table lengkap (nomor port, tipe access/trunk, VLAN, perangkat tujuan).",
        ],
        set(),
    ),
    (
        "J.611000.004.01",
        "Merancang Pengalamatan Jaringan",
        [
            "Tabel IP Addressing lengkap (VLAN, Divisi, Network, Prefix, Gateway, Broadcast, Usable Range, DHCP Range, Jumlah User) sesuai perhitungan VLSM.",
            "Justifikasi prefix tiap VLAN dituliskan logis, sesuai kebutuhan host tiap divisi (bukan disamaratakan /24).",
        ],
        set(),
    ),
    (
        "J.611000.008.02",
        "Menyiapkan Kabel Jaringan",
        [
            "Kabel/patch cord yang dipakai diuji (cable tester atau indikator LED link) dan kabel bermasalah diganti sebelum konfigurasi dilanjutkan.",
            "Urutan pin konektor RJ45 sesuai standar T568B dan konektor terpasang kokoh (bila peserta membuat kabel sendiri).",
        ],
        set(),
    ),
    (
        "J.611000.009.02",
        "Memasang Kabel Jaringan",
        [
            "Perangkat terhubung sesuai topologi (MikroTik - Switch - AP - Client).",
            "Label kabel terpasang dengan format [SUMBER]-[TUJUAN].",
            "Link fisik tiap port dicek aktif sebelum melanjutkan konfigurasi.",
        ],
        set(),
    ),
    (
        "J.611000.010.02",
        "Memasang Jaringan Nirkabel",
        [
            "Port ke AP dicatat dan dikonfigurasi sebagai access port VLAN 30 (bukan trunk).",
            "AP dikonfigurasi SSID ND-GUEST, keamanan WPA2-PSK minimal, max-station 15.",
            "Uplink AP ke switch berupa access port VLAN 30, tanpa konfigurasi VLAN apa pun di sisi AP.",
            "Port AP di switch diverifikasi sebagai access VLAN 30, bukan trunk.",
        ],
        set(),
    ),
    (
        "J.611000.011.02",
        "Memasang Perangkat Jaringan ke dalam Sistem Jaringan",
        [
            "Identity router sesuai format UKK_[NO_ABSEN]_[NAMA_PESERTA].",
            "Interface ether1-WAN dan ether2-LAN dikonfigurasi dengan benar.",
            "IP WAN static (192.168.205.X/24) dan gateway (192.168.205.1/24) terpasang sesuai penugasan asesor.",
            "DNS primary 1.1.1.1 dan secondary 8.8.8.8 terpasang.",
            "Default route ke gateway ISP terpasang.",
            "VLAN 10/20/30 dibuat di router dengan VLAN-ID benar, master interface ether2.",
            "Port switch dikonfigurasi trunk ke router, membawa VLAN 10/20/30 tagged.",
            "Port switch access dikonfigurasi sesuai denah: Management (VLAN 10), Staff (VLAN 20), AP (VLAN 30).",
            "IP address tiap interface VLAN sesuai prefix pada tabel IP Addressing.",
            "DHCP Server dibuat untuk tiga VLAN (DHCP-MANAGEMENT, DHCP-STAFF, DHCP-GUEST).",
            "Pool DHCP (POOL-[DIVISI]) sesuai range pada tabel IP Addressing.",
            "NAT/Masquerade dikonfigurasi dengan comment NAT-INTERNET-ACCESS.",
            "Konfigurasi router diuji ulang dan dibuktikan berfungsi sebelum penilaian dilanjutkan.",
        ],
        {12},
    ),
    (
        "J.611000.012.02",
        "Mengkonfigurasi Switch pada Jaringan",
        [
            "VLAN 10/20/30 dibuat pada switch dengan VLAN-ID yang benar.",
            "Port trunk ke router dikonfigurasi dan membawa VLAN 10/20/30 tagged.",
            "Port access dikonfigurasi sesuai denah: Management (VLAN 10), Staff (VLAN 20), AP (VLAN 30).",
            "Konfigurasi switch diverifikasi dan trafik tiap segmen terbukti berjalan.",
        ],
        set(),
    ),
    (
        "J.611000.006.01",
        "Merancang Keamanan Jaringan",
        [
            "Comment rule menggunakan format FW-[FUNGSI] secara konsisten.",
            "Rule FW-BLOCK-GUEST-TO-MGMT aktif dan terbukti berfungsi.",
            "Rule FW-BLOCK-GUEST-TO-STAFF aktif dan terbukti berfungsi.",
            "Rule FW-BLOCK-STAFF-TO-MGMT aktif dan terbukti berfungsi.",
            "Rule FW-ALLOW-WINBOX-MGMT (port 8291 dari Management) aktif.",
            "Rule FW-DROP-WINBOX-OTHERS (port 8291 dari selain Management) aktif.",
            "User baru UKK[NO_ABSEN] dengan password sesuai ketentuan berhasil dibuat.",
            "User admin default dinonaktifkan atau password-nya diganti.",
            "Service tidak terpakai (telnet, ftp, www, api, api-ssl) dinonaktifkan; winbox dan ssh tetap aktif.",
            "Rule FW-ALLOW-ESTABLISHED (established, related) dibuat dan ditempatkan sebelum rule drop.",
            "Rule FW-DROP-INVALID (connection-state invalid) dibuat pada chain yang sesuai dan urutan rule firewall benar.",
        ],
        set(),
    ),
    (
        "J.611000.015.02",
        "Memonitor Keamanan dan Pengaturan Akun Pengguna dalam Jaringan Komputer",
        [
            "Ping Guest ke Management gagal, sesuai firewall.",
            "Ping Staff ke Management gagal, sesuai firewall.",
            "Winbox dari Guest gagal (diblokir firewall).",
        ],
        set(),
    ),
    (
        "J.611000.020.01",
        "Mengoptimalkan Kinerja Sistem Jaringan",
        [
            "QUEUE-GUEST terpasang dengan max-limit 2M/2M.",
            "QUEUE-MGMT-STAFF terpasang dengan max-limit 8M/8M.",
            "Queue type PCQ dibuat dan diterapkan pada VLAN Staff dengan classifier src-address/dst-address yang sesuai.",
            "Pembagian bandwidth per client terbukti merata saat diuji dengan minimal dua client.",
            "Mangle mark-connection dan mark-packet dibuat dengan comment MANGLE-[FUNGSI].",
            "Queue tree memakai packet-mark dengan limit sesuai kebijakan (Guest 2M, Management-Staff 8M).",
            "Prioritas trafik (priority) diterapkan sehingga trafik Management lebih diutamakan daripada Guest.",
            "Limit bandwidth diverifikasi dengan speedtest atau bandwidth-test dan hasilnya dicatat pada report sheet.",
            "Torch atau Traffic Monitor digunakan untuk membuktikan trafik per interface VLAN.",
        ],
        set(),
    ),
    (
        "J.611000.017.01",
        "Mengidentifikasi Sumber Kerusakan",
        [
            "Gejala gangguan yang disisipkan asesor diidentifikasi dan dugaan penyebab dicatat.",
            "Penyebab diisolasi secara sistematis per lapisan (fisik, VLAN, IP, firewall/NAT) menggunakan ping, traceroute, atau print konfigurasi.",
        ],
        set(),
    ),
    (
        "J.611000.018.02",
        "Memperbaiki Kerusakan Konfigurasi Jaringan",
        [
            "Gangguan diperbaiki dan dibuktikan dengan pengujian ulang.",
            "Perbaikan dicatat pada report sheet.",
        ],
        set(),
    ),
    (
        "J.611000.022.01",
        "Melakukan Backup dan Restore Konfigurasi Perangkat Jaringan",
        [
            "File .backup berhasil dibuat.",
            "File .rsc (export configuration) berhasil dibuat.",
            "Nama file backup sesuai format UKK_[NO_ABSEN]_[NAMA_PESERTA]_BACKUP.",
            "Restore konfigurasi dari file backup berhasil dan perangkat kembali berfungsi.",
        ],
        {3},
    ),
]

SUB_COMPETENCIES: list[tuple[str, str, int, list[str]]] = [
    ("SK-01", "Perancang Jaringan Muda", 1, ["J.611000.003.02", "J.611000.004.01"]),
    (
        "SK-02",
        "Teknisi Instalasi Jaringan",
        2,
        [
            "J.611000.008.02",
            "J.611000.009.02",
            "J.611000.010.02",
            "J.611000.011.02",
        ],
    ),
    (
        "SK-03",
        "Teknisi Konfigurasi Jaringan",
        3,
        ["J.611000.004.01", "J.611000.011.02", "J.611000.012.02"],
    ),
    (
        "SK-04",
        "Teknisi Keamanan & Trafik Jaringan",
        4,
        ["J.611000.006.01", "J.611000.015.02", "J.611000.020.01"],
    ),
    (
        "SK-05",
        "Teknisi Troubleshooting & Pemulihan",
        5,
        ["J.611000.017.01", "J.611000.018.02", "J.611000.022.01"],
    ),
]

# Instrumen Skema Tambahan 1: LSA-PRO (Linux System & Server Administrator)
EXTRA_SCHEME_DATA: dict[str, dict[str, Any]] = {
    "LSA-PRO": {
        "prefix": "LSA",
        "units": [
            (
                "LSA.01.001",
                "Mengelola Partisi, LVM, dan Hak Akses Sistem File Linux",
                [
                    "Volume Group dan Logical Volume (LVM) berhasil dibuat dan di-mount permanen melalui /etc/fstab.",
                    "Permission direktori kolaborasi diatur menggunakan SGID dan ACL sesuai kebijakan grup.",
                    "Kuota disk pengguna dikonfigurasi dan diverifikasi aktif.",
                ],
            ),
            (
                "LSA.02.002",
                "Melakukan Hardening SSH dan Konfigurasi Firewall Server",
                [
                    "Login root via SSH dinonaktifkan, autentikasi berbasis SSH Key diterapkan pada port kustom.",
                    "Firewall (UFW/nftables) memblokir seluruh port masuk kecuali port layanan resmi yang diizinkan.",
                    "Layanan Fail2Ban aktif memproteksi brute-force pada SSH.",
                ],
            ),
            (
                "LSA.03.003",
                "Mengkonfigurasi Web Server, Reverse Proxy, dan TLS/SSL",
                [
                    "Nginx beroperasi sebagai reverse proxy ke aplikasi backend dengan header keamanan lengkap.",
                    "Sertifikat TLS terpasang dengan redirect otomatis HTTP ke HTTPS.",
                    "uji beban dan validasi konfigurasi (nginx -t) berjalan tanpa error.",
                ],
            ),
            (
                "LSA.04.004",
                "Automasi Backup Sistem dan Pemantauan Layanan (Systemd/Cron)",
                [
                    "Script Bash backup memakai strict mode (set -euo pipefail) dan menghasilkan arsip terenkripsi.",
                    "Systemd timer / cronjob terjadwal berjalan otomatis dan mencatat log status eksekusi.",
                    "Simulasi restore data berhasil memulihkan layanan dalam batas waktu RTO.",
                ],
            ),
        ],
        "subs": [
            ("LSA-SK1", "Junior Linux System Administrator", 1, ["LSA.01.001", "LSA.02.002"]),
            ("LSA-SK2", "Linux Infrastructure & WebOps Engineer", 2, ["LSA.03.003", "LSA.04.004"]),
        ],
    },
    "CNA-MTC": {
        "prefix": "CNA",
        "units": [
            (
                "CNA.01.001",
                "Mengimplementasikan VLAN Trunking dan Redundansi Layer-2 (STP)",
                [
                    "Inter-VLAN routing dan trunk 802.1Q berjalan normal antar switch distribusi dan akses.",
                    "Rapid Spanning Tree Protocol (RSTP) dikonfigurasi dengan root bridge utama dan cadangan yang tepat.",
                    "Fitur BPDU Guard dan Port Security aktif pada seluruh port akses klien.",
                ],
            ),
            (
                "CNA.02.002",
                "Mengkonfigurasi Dynamic Routing Multi-Area OSPF",
                [
                    "Tetangga OSPF (adjacency FULL) terbentuk sempurna menggunakan autentikasi MD5/SHA.",
                    "Tabel routing menerima prefix antar-area dan melakukan failover otomatis saat link utama putus.",
                    "Passive-interface diterapkan pada seluruh jaringan LAN/pengguna akhir.",
                ],
            ),
            (
                "CNA.03.003",
                "Membangun Tunneling VPN Site-to-Site Berbasis IPSec",
                [
                    "Fase 1 (IKE) dan Fase 2 (ESP) tunnel terbentuk dengan enkripsi AES-256.",
                    "Trafik antar kantor cabang melewati tunnel terenkripsi tanpa kebocoran paket ke publik.",
                    "Keepalive / Dead Peer Detection (DPD) berhasil memulihkan sesi saat koneksi di-reset.",
                ],
            ),
            (
                "CNA.04.004",
                "Memonitor Performa Jaringan dan Dokumentasi Insiden",
                [
                    "SNMPv3 dan pengiriman Syslog terpusat ke server monitoring terverifikasi berjalan.",
                    "Analisis latensi dan packet loss terdokumentasi lengkap beserta rekomendasi optimasi QoS.",
                    "Backup konfigurasi seluruh node router/switch tersimpan dengan penamaan standar.",
                ],
            ),
        ],
        "subs": [
            ("CNA-SK1", "Associate Switching & Routing Specialist", 1, ["CNA.01.001", "CNA.02.002"]),
            ("CNA-SK2", "Network Security & VPN Specialist", 2, ["CNA.03.003", "CNA.04.004"]),
        ],
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "pass_threshold": 70,
    "predicate_sangat_mahir": 90,
    "predicate_mahir": 80,
    "predicate_cakap": 70,
    "instrument_version": 1,
    "instrument_updated_at": "2026-11-06T00:00:00Z",
    "sheet_tab_prefix": "UKK",
    "active_scheme_kode": DEFAULT_SCHEME_KODE,
    "templates": SCHEMES[0]["templates"],
}


def seed(conn: sqlite3.Connection) -> None:
    """Isi skema asesmen, instrumen default, & config bila belum tersedia."""
    stamp = "2026-11-06T00:00:00Z"

    # 1. Seed daftar skema
    for scheme in SCHEMES:
        conn.execute(
            """
            INSERT OR IGNORE INTO scheme
                (kode, nama, kategori, deskripsi, pass_threshold,
                 predicate_sangat_mahir, predicate_mahir, predicate_cakap,
                 templates_json, aktif, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (
                scheme["kode"],
                scheme["nama"],
                scheme["kategori"],
                scheme["deskripsi"],
                scheme["pass_threshold"],
                scheme["predicate_sangat_mahir"],
                scheme["predicate_mahir"],
                scheme["predicate_cakap"],
                json.dumps(scheme["templates"], ensure_ascii=False),
                stamp,
                stamp,
            ),
        )

    # 2. Seed instrumen utama JNT-SMK (13 unit, 61 indikator) bila belum ada
    jnt_count = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE scheme_kode = ?", (DEFAULT_SCHEME_KODE,)
    ).fetchone()[0]
    if jnt_count == 0:
        global_no = 1
        for urutan, (kode, judul, indicators, proposed_indexes) in enumerate(UNITS, start=1):
            conn.execute(
                """
                INSERT INTO unit
                    (kode, scheme_kode, judul, urutan, aktif, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (kode, DEFAULT_SCHEME_KODE, judul, urutan, stamp, stamp),
            )
            for i, teks in enumerate(indicators, start=1):
                ind_kode = f"IND-{global_no:03d}"
                is_proposed = 1 if (i - 1) in proposed_indexes else 0
                conn.execute(
                    """
                    INSERT INTO indicator
                        (kode, unit_kode, teks, urutan, aktif, version, is_proposed, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?)
                    """,
                    (ind_kode, kode, teks, i, is_proposed, stamp, stamp),
                )
                global_no += 1

        for sub_kode, judul, urutan, unit_kodes in SUB_COMPETENCIES:
            conn.execute(
                """
                INSERT INTO sub_competency
                    (kode, scheme_kode, judul, urutan, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (sub_kode, DEFAULT_SCHEME_KODE, judul, urutan, stamp, stamp),
            )
            for unit_kode in unit_kodes:
                conn.execute(
                    """
                    INSERT INTO sub_competency_unit (sub_competency_kode, unit_kode)
                    VALUES (?, ?)
                    """,
                    (sub_kode, unit_kode),
                )

    # 3. Seed skema tambahan (LSA-PRO & CNA-MTC)
    for scheme_kode, spec in EXTRA_SCHEME_DATA.items():
        existing_units = conn.execute(
            "SELECT COUNT(*) FROM unit WHERE scheme_kode = ?", (scheme_kode,)
        ).fetchone()[0]
        if existing_units > 0:
            continue
        prefix = spec["prefix"]
        seq = 1
        for urutan, (unit_kode, judul, indicators) in enumerate(spec["units"], start=1):
            conn.execute(
                """
                INSERT OR IGNORE INTO unit
                    (kode, scheme_kode, judul, urutan, aktif, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (unit_kode, scheme_kode, judul, urutan, stamp, stamp),
            )
            for i, teks in enumerate(indicators, start=1):
                ind_kode = f"{prefix}-{seq:03d}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO indicator
                        (kode, unit_kode, teks, urutan, aktif, version, is_proposed, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, 1, 0, ?, ?)
                    """,
                    (ind_kode, unit_kode, teks, i, stamp, stamp),
                )
                seq += 1
        for sub_kode, judul, urutan, unit_kodes in spec["subs"]:
            conn.execute(
                """
                INSERT OR IGNORE INTO sub_competency
                    (kode, scheme_kode, judul, urutan, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (sub_kode, scheme_kode, judul, urutan, stamp, stamp),
            )
            for unit_kode in unit_kodes:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sub_competency_unit (sub_competency_kode, unit_kode)
                    VALUES (?, ?)
                    """,
                    (sub_kode, unit_kode),
                )

    # 4. Seed default config
    for key, value in DEFAULT_CONFIG.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO config (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, json.dumps(value), stamp),
        )
    conn.commit()
