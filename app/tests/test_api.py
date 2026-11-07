"""Tes API end-to-end dengan TestClient dan database sementara."""

from __future__ import annotations

import io
import os

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
    response = client.post("/api/assessments", json={"participant_id": participant_id}, headers=H)
    assert response.status_code in (200, 201), response.text
    return response.json()


def all_indicator_items(payload: dict, value: int = 3) -> list[dict]:
    return [
        {"indicator_kode": ind["kode"], "value": value}
        for unit in payload["units"]
        for ind in unit["indicators"]
    ]


def test_health_dan_seed(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["units"] == 13
    assert data["indicators"] == 61


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
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["result"]["outcome"] == "kompeten_penuh"

    response = client.get(f"/api/schools/{school['id']}/export?format=csv")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert b"nomor,nama,kelas" in response.content

    response = client.get(f"/api/schools/{school['id']}/export?format=xlsx")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["Ringkasan", "Detail Unit", "Sub Kompetensi"]


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

