"""Tes render sertifikat 2 halaman (halaman depan + halaman belakang unit kompetensi lulus)."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

import pytest
from fastapi import HTTPException

import exams


def _build_two_page_docx(unit_rows: int = 8, loop_mode: bool = False, extra_placeholder: str = "") -> bytes:
    front_text = (
        "No {{certificate_number}} | {{participant_name}} ({{participant_number}}) | "
        "{{exam_title}} {{exam_year}} {{scheme_name}} di {{school_name}} {{exam_date}} | "
        "{{outcome_label}} / {{outcome_label_en}} | {{issued_date}}"
    )
    if extra_placeholder:
        front_text += f" | {extra_placeholder}"

    if loop_mode:
        body_rows = (
            "<w:tr>"
            "<w:tc><w:p><w:r><w:t>{{unit_no}}.</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>{{unit_code}}</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>{{unit_title}}</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
        )
    else:
        body_rows = "".join(
            f"<w:tr>"
            f"<w:tc><w:p><w:r><w:t>{i}.</w:t></w:r></w:p></w:tc>"
            f"<w:tc><w:p><w:r><w:t>{{{{unit_{i}_code}}}}</w:t></w:r></w:p></w:tc>"
            f"<w:tc><w:p><w:r><w:t>{{{{unit_{i}_title}}}}</w:t></w:r></w:p></w:tc>"
            f"</w:tr>"
            for i in range(1, unit_rows + 1)
        )

    document_xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f"<w:p><w:r><w:t>{front_text}</w:t></w:r></w:p>"
        '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
        "<w:p><w:r><w:t>UNIT KOMPETENSI</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>No</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Kode Unit</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Unit Kompetensi</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        f"{body_rows}"
        "</w:tbl>"
        "<w:p><w:r><w:t>Penguji: {{examiner_name}} | Peserta: {{participant_name}} ({{participant_number}})</w:t></w:r></w:p>"
        "<w:sectPr/>"
        "</w:body></w:document>"
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": document_xml,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buf.getvalue()


def _read_table_rows(docx_path) -> list[list[str]]:
    with zipfile.ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    tbl = root.find(f".//{{{exams.W_NS}}}tbl")
    assert tbl is not None
    rows: list[list[str]] = []
    for tr in tbl.findall(f"{{{exams.W_NS}}}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{{{exams.W_NS}}}tc"):
            cells.append("".join(t.text or "" for t in tc.iter(f"{{{exams.W_NS}}}t")))
        rows.append(cells)
    return rows


def _read_all_text(docx_path) -> str:
    with zipfile.ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    return "\n".join("".join(t.text or "" for t in p.iter(f"{{{exams.W_NS}}}t")) for p in root.iter(f"{{{exams.W_NS}}}p"))


def _sample_enrollment() -> dict:
    return {
        "snapshot_name": "Budi Santoso",
        "snapshot_number": "07",
        "group_label": "XII TKJ 1",
        "snapshot_class": "XII TKJ 1",
        "snapshot_school_name": "SMK Negeri 1",
        "exam_title": "Uji Kompetensi Keahlian",
        "exam_year": 2026,
        "starts_on": "2026-11-16",
        "ends_on": "2026-11-18",
        "scheme_name": "Junior Network Technician",
    }


def _sample_result(passed_count: int) -> dict:
    unit_results = []
    for i in range(1, 14):
        unit_results.append(
            {
                "kode": f"J.611000.{i:03d}.01",
                "judul": f"Unit Kompetensi {i}",
                "urutan": i,
                "percent": 100.0 if i <= passed_count else 40.0,
                "passed": i <= passed_count,
            }
        )
    return {
        "outcome": "kompeten_penuh" if passed_count == 13 else "kompeten_sub",
        "outcome_label": "Kompeten Penuh" if passed_count == 13 else "Kompeten pada Sub Kompetensi",
        "predicate": "Sangat Mahir",
        "unit_results": unit_results,
        "selected_sub": {"kode": "SK-02", "judul": "Teknisi Instalasi Jaringan"},
    }


def test_validate_docx_menerima_template_dua_halaman_dan_menolak_unknown():
    raw_ok = _build_two_page_docx(unit_rows=8)
    placeholders, _ = exams._validate_docx(raw_ok)
    assert "outcome_label_en" in placeholders
    assert "examiner_name" in placeholders
    assert "unit_1_code" in placeholders
    assert "unit_8_title" in placeholders

    raw_bad = _build_two_page_docx(unit_rows=4, extra_placeholder="{{tidak_dikenal}}")
    with pytest.raises(HTTPException) as exc:
        exams._validate_docx(raw_bad)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "unknown_placeholders"


def test_render_dua_halaman_pruning_baris_kosong(tmp_path):
    raw = _build_two_page_docx(unit_rows=8)
    values, passed_units = exams._certificate_values(
        _sample_enrollment(), _sample_result(passed_count=4), "AA-2026-JNT-SMK-00001", examiner_name="Welly Chandra"
    )
    out = tmp_path / "out_4.docx"
    exams._render_docx(raw, values, out, passed_units=passed_units)

    rows = _read_table_rows(out)
    assert len(rows) == 5  # 1 header + 4 unit lulus (baris 5..8 otomatis dihapus)
    assert rows[1] == ["1.", "J.611000.001.01", "Unit Kompetensi 1"]
    assert rows[4] == ["4.", "J.611000.004.01", "Unit Kompetensi 4"]

    text = _read_all_text(out)
    assert "Competent in Sub-Competency" in text
    assert "Penguji: Welly Chandra" in text
    assert "{{" not in text


def test_render_dua_halaman_otomatis_tambah_baris_jika_unit_lebih_banyak(tmp_path):
    raw = _build_two_page_docx(unit_rows=8)
    values, passed_units = exams._certificate_values(
        _sample_enrollment(), _sample_result(passed_count=13), "AA-2026-JNT-SMK-00002", examiner_name="Welly Chandra"
    )
    out = tmp_path / "out_13.docx"
    exams._render_docx(raw, values, out, passed_units=passed_units)

    rows = _read_table_rows(out)
    assert len(rows) == 14  # 1 header + 13 unit lulus (baris 9..13 otomatis di-clone)
    assert rows[8] == ["8.", "J.611000.008.01", "Unit Kompetensi 8"]
    assert rows[9] == ["9.", "J.611000.009.01", "Unit Kompetensi 9"]
    assert rows[13] == ["13.", "J.611000.013.01", "Unit Kompetensi 13"]

    text = _read_all_text(out)
    assert "Fully Competent" in text
    assert "{{" not in text


def test_render_dua_halaman_mode_loop_baris_dinamis(tmp_path):
    raw = _build_two_page_docx(loop_mode=True)
    placeholders, _ = exams._validate_docx(raw)
    assert {"unit_no", "unit_code", "unit_title"} <= set(placeholders)

    values, passed_units = exams._certificate_values(
        _sample_enrollment(), _sample_result(passed_count=5), "AA-2026-JNT-SMK-00003", examiner_name="Welly Chandra"
    )
    out = tmp_path / "out_loop.docx"
    exams._render_docx(raw, values, out, passed_units=passed_units)

    rows = _read_table_rows(out)
    assert len(rows) == 6  # 1 header + 5 unit lulus
    assert rows[1] == ["1.", "J.611000.001.01", "Unit Kompetensi 1"]
    assert rows[5] == ["5.", "J.611000.005.01", "Unit Kompetensi 5"]


def test_bulk_generate_sertifikat_per_kelas_dan_download_zip(tmp_path, monkeypatch):
    import pyotp
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_ID", raising=False)
    monkeypatch.setattr(exams, "_convert_docx_to_pdf", lambda docx_path, work_dir: b"%PDF-1.4\n%fake\n")

    app = main.create_app(tmp_path / "bulk.db")
    headers = {"X-Requested-With": "fetch"}
    with TestClient(app) as client:
        secret = client.post("/api/auth/setup", json={"username": "asesor", "password": "rahasia123"}, headers=headers).json()["secret"]
        client.post("/api/auth/login", json={"username": "asesor", "password": "rahasia123", "totp": pyotp.TOTP(secret).now()}, headers=headers)

        school = client.post("/api/schools", json={"nama": "SMK Bulk 1"}, headers=headers).json()
        p1 = client.post(f"/api/schools/{school['id']}/participants", json={"nomor": "01", "nama": "Andi", "kelas": "XII TKJ 1"}, headers=headers).json()
        p2 = client.post(f"/api/schools/{school['id']}/participants", json={"nomor": "02", "nama": "Budi", "kelas": "XII TKJ 1"}, headers=headers).json()
        p3 = client.post(f"/api/schools/{school['id']}/participants", json={"nomor": "03", "nama": "Cici", "kelas": "XII TKJ 1"}, headers=headers).json()
        p4 = client.post(f"/api/schools/{school['id']}/participants", json={"nomor": "04", "nama": "Dedi", "kelas": "XII TKJ 2"}, headers=headers).json()

        exam = client.post(
            "/api/exams",
            json={"title": "UKK 2026", "year": 2026, "school_ids": [school["id"]], "scheme_kodes": [school["scheme_kode"]]},
            headers=headers,
        ).json()
        client.post(f"/api/exams/{exam['id']}/activate", headers=headers)

        enrolls = {}
        for p in (p1, p2, p3, p4):
            e = client.post(
                f"/api/exams/{exam['id']}/enrollments",
                json={"participant_id": p["id"], "scheme_kode": school["scheme_kode"], "group_label": p["kelas"]},
                headers=headers,
            ).json()
            enrolls[p["nomor"]] = e

        # Cek exam.groups terisi otomatis
        exam_detail = client.get(f"/api/exams/{exam['id']}").json()
        assert exam_detail["groups"] == ["XII TKJ 1", "XII TKJ 2"]

        # p1 & p2 (XII TKJ 1) kompeten penuh, p3 (XII TKJ 1) belum kompeten, p4 (XII TKJ 2) kompeten penuh
        for nomor, score_val in (("01", 3), ("02", 3), ("03", 0), ("04", 3)):
            e = enrolls[nomor]
            asm = client.post("/api/assessments", json={"participant_id": e["participant_id"], "enrollment_id": e["id"]}, headers=headers).json()
            items = [{"indicator_kode": ind["kode"], "value": score_val} for u in asm["units"] for ind in u["indicators"]]
            client.patch(f"/api/assessments/{asm['assessment']['id']}/scores", json={"items": items}, headers=headers)
            client.post(f"/api/assessments/{asm['assessment']['id']}/lock", json={}, headers=headers)

        # Upload, preview, dan aktifkan template 2 halaman
        tpl = client.post(
            "/api/certificate-templates",
            data={"exam_id": str(exam["id"])},
            files={"file": ("axelbit-2hal.docx", _build_two_page_docx(unit_rows=8), "application/octet-stream")},
            headers=headers,
        ).json()
        assert client.post(f"/api/certificate-templates/{tpl['id']}/preview", headers=headers).status_code == 200
        assert client.post(f"/api/certificate-templates/{tpl['id']}/activate", headers=headers).status_code == 200

        # Bulk generate khusus kelas XII TKJ 1
        bulk = client.post(
            f"/api/exams/{exam['id']}/certificates/bulk",
            json={"template_id": tpl["id"], "group_label": "XII TKJ 1", "examiner_name": "Welly Chandra"},
            headers=headers,
        )
        assert bulk.status_code == 200, bulk.text
        data = bulk.json()
        assert data["total_matched"] == 3
        assert data["issued"] == 2
        assert data["skipped_not_competent"] == 1
        assert data["already_issued"] == 0
        assert data["errors"] == []

        # Jalankan ulang tanpa reissue -> idempoten (already_issued = 2, issued = 0)
        bulk_again = client.post(
            f"/api/exams/{exam['id']}/certificates/bulk",
            json={"template_id": tpl["id"], "group_label": "XII TKJ 1"},
            headers=headers,
        ).json()
        assert bulk_again["issued"] == 0
        assert bulk_again["already_issued"] == 2

        # Download ZIP khusus kelas XII TKJ 1 -> berisi tepat 2 PDF (Andi & Budi)
        zip_res = client.get(f"/api/exams/{exam['id']}/certificates/download-zip?group_label=XII+TKJ+1")
        assert zip_res.status_code == 200
        assert zip_res.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
            names = sorted(zf.namelist())
            assert len(names) == 2
            assert any("Andi" in n for n in names)
            assert any("Budi" in n for n in names)
            assert all(zf.read(n).startswith(b"%PDF-") for n in names)

