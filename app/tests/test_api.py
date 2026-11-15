"""Tes API end-to-end dengan TestClient dan database sementara."""

from __future__ import annotations

import io
import os
import zipfile

import pyotp
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import auth
import main
import sheets

H = {"X-Requested-With": "fetch"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_ID", raising=False)
    monkeypatch.setenv("SYNC_API_KEY", "test-sync-key")
    app = main.create_app(tmp_path / "test.db")
    with TestClient(app) as test_client:
        yield test_client


def setup_login(client: TestClient) -> str:
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json()["needs_setup"] is True
    response = client.post(
        "/api/auth/setup",
        json={"username": "asesor", "password": "rahasia123"},
        headers=H,
    )
    assert response.status_code == 200, response.text
    secret = response.json()["secret"]
    code = pyotp.TOTP(secret).now()
    response = client.post(
        "/api/auth/login",
        json={"username": "asesor", "password": "rahasia123", "totp": code},
        headers=H,
    )
    assert response.status_code == 200, response.text
    return secret


def make_school(client: TestClient, nama: str = "SMK Negeri 1") -> dict:
    response = client.post("/api/schools", json={"nama": nama}, headers=H)
    assert response.status_code == 201, response.text
    return response.json()


def make_participant(client: TestClient, school_id: int, nomor: str = "01", nama: str = "Ahmad") -> dict:
    response = client.post(
        f"/api/schools/{school_id}/participants",
        json={"nomor": nomor, "nama": nama, "kelas": "XII TKJ"},
        headers=H,
    )
    assert response.status_code == 201, response.text
    return response.json()


def start_assessment(client: TestClient, participant_id: int) -> dict:
    participant = None
    for school in client.get("/api/schools").json()["data"]:
        participants = client.get(f"/api/schools/{school['id']}/participants").json()["data"]
        participant = next((row for row in participants if row["id"] == participant_id), None)
        if participant:
            break
    assert participant is not None
    exam_count = client.get("/api/exams").json()["meta"]["total"]
    exam = client.post(
        "/api/exams",
        json={
            "title": f"Uji otomatis {exam_count + 1}",
            "year": 2030,
            "school_ids": [participant["school_id"]],
            "scheme_kodes": [school["scheme_kode"]],
        },
        headers=H,
    )
    assert exam.status_code == 201, exam.text
    exam_id = exam.json()["id"]
    assert client.post(f"/api/exams/{exam_id}/activate", headers=H).status_code == 200
    enrollment = client.post(
        f"/api/exams/{exam_id}/enrollments",
        json={
            "participant_id": participant_id,
            "scheme_kode": school["scheme_kode"],
            "group_label": participant.get("kelas", ""),
        },
        headers=H,
    )
    assert enrollment.status_code == 201, enrollment.text
    response = client.post(
        "/api/assessments",
        json={
            "participant_id": participant_id,
            "enrollment_id": enrollment.json()["id"],
        },
        headers=H,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def all_indicator_items(payload: dict, value: int = 3) -> list[dict]:
    return [
        {"indicator_kode": ind["kode"], "value": value}
        for unit in payload["units"]
        for ind in unit["indicators"]
    ]


def certificate_docx(placeholders: list[str] | None = None) -> bytes:
    names = placeholders or [
        "participant_name",
        "participant_number",
        "school_name",
        "exam_title",
        "exam_year",
        "scheme_name",
        "outcome_label",
        "certificate_number",
        "issued_date",
    ]
    text = " · ".join(f"{{{{{name}}}}}" for name in names)
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
        "word/document.xml": (
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p><w:sectPr/></w:body></w:document>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def test_health_dan_seed(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["units"] == 13
    assert data["indicators"] == 61


def test_exam_roster_dashboard_archive_and_export(client):
    setup_login(client)
    school = make_school(client)
    peserta = [
        make_participant(client, school["id"], f"{index:02d}", f"Peserta {index}")
        for index in range(1, 5)
    ]
    body = {
        "title": "Ujian Tahunan",
        "year": 2034,
        "starts_on": "2034-05-01",
        "ends_on": "2034-05-03",
        "school_ids": [school["id"]],
        "scheme_kodes": [school["scheme_kode"]],
    }
    created = client.post("/api/exams", json=body, headers=H)
    assert created.status_code == 201, created.text
    exam = created.json()
    assert exam["status"] == "draft"

    duplicate = client.post("/api/exams", json=body, headers=H)
    assert duplicate.status_code == 409
    next_year = client.post("/api/exams", json={**body, "year": 2035}, headers=H)
    assert next_year.status_code == 201

    enrollments = []
    for participant in peserta:
        response = client.post(
            f"/api/exams/{exam['id']}/enrollments",
            json={
                "participant_id": participant["id"],
                "scheme_kode": school["scheme_kode"],
                "group_label": "XII TKJ 1",
            },
            headers=H,
        )
        assert response.status_code == 201, response.text
        enrollments.append(response.json())

    duplicate_enrollment = client.post(
        f"/api/exams/{exam['id']}/enrollments",
        json={
            "participant_id": peserta[0]["id"],
            "scheme_kode": school["scheme_kode"],
            "group_label": "XII TKJ 1",
        },
        headers=H,
    )
    assert duplicate_enrollment.status_code == 409

    before_active = client.post(
        "/api/assessments",
        json={"participant_id": peserta[0]["id"], "enrollment_id": enrollments[0]["id"]},
        headers=H,
    )
    assert before_active.status_code == 409
    assert client.post(f"/api/exams/{exam['id']}/activate", headers=H).status_code == 200

    first = client.post(
        "/api/assessments",
        json={"participant_id": peserta[0]["id"], "enrollment_id": enrollments[0]["id"]},
        headers=H,
    )
    second = client.post(
        "/api/assessments",
        json={"participant_id": peserta[1]["id"], "enrollment_id": enrollments[1]["id"]},
        headers=H,
    )
    assert first.status_code == second.status_code == 201
    first_payload, second_payload = first.json(), second.json()
    assert first_payload["assessment"]["exam"]["exam_title"] == "Ujian Tahunan"
    assert first_payload["assessment"]["exam"]["exam_year"] == 2034

    for payload, score in ((first_payload, 3), (second_payload, 0)):
        saved = client.patch(
            f"/api/assessments/{payload['assessment']['id']}/scores",
            json={"items": all_indicator_items(payload, score)},
            headers=H,
        )
        assert saved.status_code == 200, saved.text
        locked = client.post(
            f"/api/assessments/{payload['assessment']['id']}/lock",
            json={"confirm_empty": False},
            headers=H,
        )
        assert locked.status_code == 200, locked.text

    withdrawn = client.post(
        f"/api/exams/{exam['id']}/enrollments/{enrollments[3]['id']}/withdraw",
        headers=H,
    )
    assert withdrawn.status_code == 200
    dashboard = client.get(f"/api/exams/dashboard?exam_id={exam['id']}").json()["stats"]
    assert dashboard["total"] == 3
    assert dashboard["assessed"] == 2
    assert dashboard["passed"] == 1
    assert dashboard["failed"] == 1
    assert dashboard["pass_percent"] == dashboard["fail_percent"] == 50
    assert dashboard["not_started"] == 1
    assert dashboard["completion_percent"] == 66.67

    assert client.post(f"/api/exams/{exam['id']}/close", headers=H).status_code == 200
    archived = client.post(f"/api/exams/{exam['id']}/archive", headers=H)
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    locked_id = first_payload["assessment"]["id"]
    mutation = client.patch(
        f"/api/assessments/{locked_id}/scores",
        json={"items": [{"indicator_kode": "IND-001", "value": 2}]},
        headers=H,
    )
    assert mutation.status_code == 409
    assert mutation.json()["error"] == "exam_archived"
    archived_list = client.get("/api/archives/exams").json()["data"]
    assert any(item["id"] == exam["id"] for item in archived_list)
    export = client.get(f"/api/exams/{exam['id']}/export?format=csv")
    assert export.status_code == 200
    assert "Ujian Tahunan" in export.text


def test_certificate_template_preview_issue_and_reissue(client):
    setup_login(client)
    school = make_school(client)
    participant = make_participant(client, school["id"])
    exam = client.post(
        "/api/exams",
        json={
            "title": "Ujian Sertifikat",
            "year": 2036,
            "school_ids": [school["id"]],
            "scheme_kodes": [school["scheme_kode"]],
        },
        headers=H,
    ).json()
    enrollment = client.post(
        f"/api/exams/{exam['id']}/enrollments",
        json={
            "participant_id": participant["id"],
            "scheme_kode": school["scheme_kode"],
            "group_label": "XII TKJ",
        },
        headers=H,
    ).json()
    assert client.post(f"/api/exams/{exam['id']}/activate", headers=H).status_code == 200
    assessment = client.post(
        "/api/assessments",
        json={"participant_id": participant["id"], "enrollment_id": enrollment["id"]},
        headers=H,
    ).json()
    assessment_id = assessment["assessment"]["id"]
    assert client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": all_indicator_items(assessment, 3)},
        headers=H,
    ).status_code == 200
    assert client.post(
        f"/api/assessments/{assessment_id}/lock", json={}, headers=H
    ).status_code == 200

    invalid = client.post(
        "/api/certificate-templates",
        data={"exam_id": str(exam["id"])},
        files={"file": ("bad.docx", b"not a zip", "application/octet-stream")},
        headers=H,
    )
    assert invalid.status_code == 400

    missing = client.post(
        "/api/certificate-templates",
        data={"exam_id": str(exam["id"])},
        files={"file": ("missing.docx", certificate_docx(["participant_name"]), "application/octet-stream")},
        headers=H,
    )
    assert missing.status_code == 400
    assert missing.json()["error"] == "required_placeholders_missing"

    uploaded = client.post(
        "/api/certificate-templates",
        data={"exam_id": str(exam["id"])},
        files={"file": ("template.docx", certificate_docx(), "application/octet-stream")},
        headers=H,
    )
    assert uploaded.status_code == 201, uploaded.text
    template_id = uploaded.json()["id"]
    activation = client.post(
        f"/api/certificate-templates/{template_id}/activate", headers=H
    )
    assert activation.status_code == 409
    preview = client.post(
        f"/api/certificate-templates/{template_id}/preview", headers=H
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.content.startswith(b"%PDF-")
    assert client.post(
        f"/api/certificate-templates/{template_id}/activate", headers=H
    ).status_code == 200

    first_issue = client.post(
        f"/api/enrollments/{enrollment['id']}/certificate",
        json={"template_id": template_id},
        headers=H,
    )
    assert first_issue.status_code == 201, first_issue.text
    first = first_issue.json()
    assert first["certificate_number"].startswith("AA-2036-JNT-SMK-")
    download = client.get(f"/api/certificates/{first['id']}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF-")

    repeat = client.post(
        f"/api/enrollments/{enrollment['id']}/certificate",
        json={"template_id": template_id},
        headers=H,
    )
    assert repeat.status_code == 201
    assert repeat.json()["id"] == first["id"]
    assert repeat.json()["already_issued"] is True
    second_issue = client.post(
        f"/api/enrollments/{enrollment['id']}/certificate",
        json={"template_id": template_id, "reissue": True},
        headers=H,
    )
    assert second_issue.status_code == 201, second_issue.text
    assert second_issue.json()["certificate_number"] != first["certificate_number"]
    issues = client.get(f"/api/enrollments/{enrollment['id']}/certificates").json()["data"]
    assert [issue["status"] for issue in issues] == ["active", "superseded"]


def test_setup_login_totp_dan_csrf(client):
    secret = setup_login(client)
    assert client.get("/api/auth/me").json()["user"]["username"] == "asesor"

    # Setup kedua ditolak
    response = client.post(
        "/api/auth/setup",
        json={"username": "lain", "password": "rahasia123"},
        headers=H,
    )
    assert response.status_code == 409

    # Mutasi tanpa header CSRF ditolak
    response = client.post("/api/schools", json={"nama": "SMK Tanpa CSRF"})
    assert response.status_code == 403
    assert response.json()["error"] == "csrf_required"

    # TOTP salah ditolak
    client.post("/api/auth/logout", headers=H)
    response = client.post(
        "/api/auth/login",
        json={"username": "asesor", "password": "rahasia123", "totp": "000000"},
        headers=H,
    )
    assert response.status_code == 401
    assert pyotp.TOTP(secret).now()


def test_crud_sekolah_dan_normalisasi(client):
    setup_login(client)
    response = client.post(
        "/api/schools",
        json={"nama": "  smk  negeri  1  ", "alamat": "  Jalan  A  "},
        headers=H,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["nama"] == "Smk Negeri 1"
    assert data["kode"] == "SMK_NEGERI_1"
    assert data["alamat"] == "Jalan A"

    response = client.post(
        "/api/schools", json={"nama": "SMK Lain", "kode": "SMK_NEGERI_1"}, headers=H
    )
    assert response.status_code == 409

    response = client.get("/api/schools")
    assert response.json()["meta"]["total"] == 1


def test_impor_csv_duplikat_dan_error(client):
    setup_login(client)
    school = make_school(client)
    content = (
        "nomor;nama;kelas\n"
        "01;Ahmad;XII TKJ\n"
        "02;Budi;XII TKJ\n"
        "02;Budi Duplikat;XII TKJ\n"
        "03;;XII TKJ\n"
    ).encode("utf-8")
    response = client.post(
        f"/api/schools/{school['id']}/participants/import",
        files={"file": ("peserta.csv", content, "text/csv")},
        headers=H,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["imported"] == 2
    assert len(data["duplicates"]) == 1
    assert len(data["errors"]) == 1

    # Impor ulang: semua nomor sudah terdaftar
    response = client.post(
        f"/api/schools/{school['id']}/participants/import",
        files={"file": ("peserta.csv", content, "text/csv")},
        headers=H,
    )
    data = response.json()
    assert data["imported"] == 0
    assert len(data["duplicates"]) == 3


def test_alur_assessment_lock_confirm_empty_unlock_dan_penuh(client):
    setup_login(client)
    school = make_school(client)
    participant = make_participant(client, school["id"])
    payload = start_assessment(client, participant["id"])
    assessment_id = payload["assessment"]["id"]
    assert len(payload["units"]) == 13
    assert payload["progress"]["total"] == 61

    first_two = [
        ind["kode"] for unit in payload["units"] for ind in unit["indicators"]
    ][:2]
    response = client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": [
            {"indicator_kode": first_two[0], "value": 3},
            {"indicator_kode": first_two[1], "value": 2, "note": "catatan"},
        ]},
        headers=H,
    )
    assert response.status_code == 200, response.text
    assert response.json()["synced"] == 2

    # Upsert idempoten: kirim ulang nilai yang sama
    response = client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": [{"indicator_kode": first_two[0], "value": 3}]},
        headers=H,
    )
    assert response.json()["synced"] == 1

    # Nilai di luar 0-3 ditolak
    response = client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": [{"indicator_kode": first_two[0], "value": 4}]},
        headers=H,
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_score"

    # Kunci tanpa konfirmasi kosong ditolak
    response = client.post(f"/api/assessments/{assessment_id}/lock", json={}, headers=H)
    assert response.status_code == 400
    assert response.json()["error"] == "empty_indicators"
    assert response.json()["count"] == 59

    # Kunci dengan konfirmasi kosong berhasil
    response = client.post(
        f"/api/assessments/{assessment_id}/lock",
        json={"confirm_empty": True},
        headers=H,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "locked"
    assert response.json()["result"]["empty_count"] == 59

    # Buka kunci wajib alasan >= 10 karakter
    response = client.post(
        f"/api/assessments/{assessment_id}/unlock", json={"reason": "pendek"}, headers=H
    )
    assert response.status_code == 400
    response = client.post(
        f"/api/assessments/{assessment_id}/unlock",
        json={"reason": "salah input unit 5"},
        headers=H,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"

    # Isi semua 61 indikator dengan 3 lalu kunci -> kompeten penuh
    response = client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": all_indicator_items(payload, 3)},
        headers=H,
    )
    assert response.status_code == 200
    assert response.json()["synced"] == 61
    response = client.post(f"/api/assessments/{assessment_id}/lock", json={}, headers=H)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["outcome"] == "kompeten_penuh"
    assert result["predicate"] == "Sangat Mahir"
    assert result["statement"] == (
        "Peserta Ahmad (01) dinyatakan kompeten sebagai Junior Network Technician "
        "dengan predikat Sangat Mahir."
    )

    response = client.get(f"/api/assessments/{assessment_id}/result")
    assert response.json()["locked"] is True
    assert response.json()["result"]["outcome"] == "kompeten_penuh"

    # Skor tidak bisa diubah setelah locked
    response = client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": [{"indicator_kode": first_two[0], "value": 0}]},
        headers=H,
    )
    assert response.status_code == 409


def test_hasil_sekolah_dan_ekspor_csv_xlsx(client):
    setup_login(client)
    school = make_school(client)
    participant = make_participant(client, school["id"])
    payload = start_assessment(client, participant["id"])
    assessment_id = payload["assessment"]["id"]
    response = client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": all_indicator_items(payload, 3)},
        headers=H,
    )
    assert response.status_code == 200
    client.post(f"/api/assessments/{assessment_id}/lock", json={}, headers=H)

    response = client.get(f"/api/schools/{school['id']}/results")
    assert response.status_code == 200
    assert response.json()["data"] == []

    exam_id = payload["assessment"]["exam"]["exam_id"]
    response = client.get(f"/api/exams/{exam_id}/export?format=csv")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert b"judul_ujian,tahun,sekolah,nomor,nama" in response.content

    response = client.get(f"/api/exams/{exam_id}/export?format=xlsx")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["Roster & Hasil"]


def test_config_version_dan_snapshot_assessment(client):
    setup_login(client)
    response = client.get("/api/config/instrument")
    assert response.json()["version"] == 1
    assert response.json()["units_count"] == 13
    assert response.json()["indicators_count"] == 61

    school = make_school(client)
    participant_a = make_participant(client, school["id"], "01", "Ahmad")
    assessment_a = start_assessment(client, participant_a["id"])
    assert assessment_a["assessment"]["instrument_version"] == 1

    response = client.post(
        "/api/config/units/J.611000.003.02/indicators",
        json={"teks": "Indikator tambahan untuk verifikasi"},
        headers=H,
    )
    assert response.status_code == 201, response.text

    response = client.get("/api/config/instrument")
    assert response.json()["version"] == 2
    assert response.json()["indicators_count"] == 62

    # Assessment lama tetap memakai snapshot 61 indikator
    response = client.get(f"/api/assessments/{assessment_a['assessment']['id']}")
    total_a = sum(len(unit["indicators"]) for unit in response.json()["units"])
    assert total_a == 61

    participant_b = make_participant(client, school["id"], "02", "Budi")
    assessment_b = start_assessment(client, participant_b["id"])
    total_b = sum(len(unit["indicators"]) for unit in assessment_b["units"])
    assert total_b == 62
    assert assessment_b["assessment"]["instrument_version"] == 2


def test_sync_status_sheets_disabled_backup_dan_api_key(client):
    setup_login(client)
    response = client.get("/api/sync/status")
    assert response.status_code == 200
    assert response.json()["sheets"]["status"] == "disabled"

    response = client.post("/api/sync/sheets", json={}, headers=H)
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    response = client.post("/api/admin/backup", headers=H)
    assert response.status_code == 200, response.text
    assert response.json()["filename"].startswith("ukk_")
    response = client.get("/api/admin/backups")
    assert len(response.json()["backups"]) == 1

    school = make_school(client)
    participant = make_participant(client, school["id"])
    payload = start_assessment(client, participant["id"])
    assessment_id = payload["assessment"]["id"]
    first_indicator = payload["units"][0]["indicators"][0]["kode"]

    # API key statis untuk worker sync internal (tanpa cookie dan tanpa CSRF header)
    client.cookies.clear()
    response = client.post(
        "/api/sync/scores",
        json={"items": [{
            "assessment_id": assessment_id,
            "indicator_kode": first_indicator,
            "value": 3,
        }]},
        headers={"X-API-Key": "test-sync-key"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["synced"] == 1

    # Tanpa API key dan tanpa sesi -> 401 (header CSRF ada agar lolos middleware)
    response = client.post(
        "/api/sync/scores",
        json={"items": [{
            "assessment_id": assessment_id,
            "indicator_kode": first_indicator,
            "value": 3,
        }]},
        headers=H,
    )
    assert response.status_code == 401


def test_rate_limiter_login():
    limiter = auth.LoginRateLimiter(limit=5, window_seconds=60)
    old = os.environ.pop("UKK_DISABLE_RATE_LIMIT", None)
    try:
        for _ in range(5):
            assert limiter.check("1.2.3.4") is True
            limiter.hit("1.2.3.4")
        assert limiter.check("1.2.3.4") is False
        assert limiter.check("9.9.9.9") is True
    finally:
        if old is not None:
            os.environ["UKK_DISABLE_RATE_LIMIT"] = old


def test_sanitasi_nama_tab_sheets():
    assert sheets.sanitize_tab_name("SMK 1/2") == "SMK_1_2"
    assert len(sheets.sanitize_tab_name("A" * 150)) == 100
    assert sheets.sanitize_tab_name("") == "Sekolah"
    assert sheets.sanitize_tab_name("History") == "Sekolah_History"


def test_multi_scheme_crud_dan_assessment_lsa_pro(client):
    setup_login(client)
    res = client.get("/api/schemes")
    assert res.status_code == 200
    schemes = {s["kode"]: s for s in res.json()["data"]}
    assert "JNT-SMK" in schemes
    assert "LSA-PRO" in schemes
    assert "CNA-MTC" in schemes
    assert schemes["LSA-PRO"]["units_count"] == 4
    assert schemes["LSA-PRO"]["indicators_count"] == 12

    # Buat skema baru
    create_res = client.post(
        "/api/schemes",
        json={
            "kode": "SEC-OPS",
            "nama": "Cyber Security Operations Analyst",
            "kategori": "Cyber Security",
            "jenjang": "Profesional",
            "pass_threshold": 75.0,
        },
        headers=H,
    )
    assert create_res.status_code == 201, create_res.text
    assert create_res.json()["kode"] == "SEC-OPS"

    # Buat sekolah dengan skema LSA-PRO
    school_res = client.post(
        "/api/schools",
        json={"nama": "TUK Axelbit Linux Academy", "scheme_kode": "LSA-PRO"},
        headers=H,
    )
    assert school_res.status_code == 201
    school = school_res.json()
    assert school["scheme_kode"] == "LSA-PRO"

    part = make_participant(client, school["id"], "01", "Rizky Linux")
    payload = start_assessment(client, part["id"])
    assessment_id = payload["assessment"]["id"]
    assert payload["assessment"]["scheme_kode"] == "LSA-PRO"
    assert len(payload["units"]) == 4
    assert payload["progress"]["total"] == 12

    client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": all_indicator_items(payload, 3)},
        headers=H,
    )
    lock_res = client.post(f"/api/assessments/{assessment_id}/lock", json={}, headers=H)
    assert lock_res.status_code == 200
    result = lock_res.json()["result"]
    assert result["outcome"] == "kompeten_penuh"
    assert "Linux System & Server Administrator" in result["statement"]


def test_recap_summary_dan_proteksi_csv_formula_injection(client):
    setup_login(client)
    school = client.post(
        "/api/schools",
        json={"nama": "SMK Cyber 1", "scheme_kode": "CNA-MTC"},
        headers=H,
    ).json()
    part = make_participant(client, school["id"], "01", "=CMD|' /C calc'!A0")
    payload = start_assessment(client, part["id"])
    assessment_id = payload["assessment"]["id"]
    client.patch(
        f"/api/assessments/{assessment_id}/scores",
        json={"items": all_indicator_items(payload, 3)},
        headers=H,
    )
    client.post(f"/api/assessments/{assessment_id}/lock", json={}, headers=H)

    recap_res = client.get("/api/recap/summary?scheme_kode=CNA-MTC")
    assert recap_res.status_code == 200
    recap_data = recap_res.json()
    assert recap_data["totals"]["participants"] == 1
    assert recap_data["outcomes"]["kompeten_penuh"] == 1
    assert len(recap_data["unit_analytics"]) == 4

    csv_res = client.get("/api/schemes/CNA-MTC/export?format=csv")
    assert csv_res.status_code == 200
    assert b"'=CMD|' /C calc'!A0" in csv_res.content

    xlsx_res = client.get("/api/schemes/CNA-MTC/export?format=xlsx")
    assert xlsx_res.status_code == 200
    wb = load_workbook(io.BytesIO(xlsx_res.content))
    assert wb.sheetnames == ["Ringkasan", "Detail Unit", "Sub Kompetensi"]
