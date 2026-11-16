"""FastAPI application untuk AeroAssess — Multi-Scheme Assessor & Competency Portal.

Penjelasan Teknis (1-2 kalimat): Aplikasi backend ini dibagi ke dalam modul registrasi route
terpisah (`_register_*_routes`) seperti pembagian tabel routing/VRF pada jaringan, sehingga
kode mudah dibaca, diuji, dan mendukung banyak skema asesmen secara simultan.
"""

from __future__ import annotations

import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from . import auth, backup, db, exams, recap, rules, sheets
except ImportError:  # pragma: no cover
    import auth  # type: ignore[no-redef]
    import backup  # type: ignore[no-redef]
    import db  # type: ignore[no-redef]
    import exams  # type: ignore[no-redef]
    import recap  # type: ignore[no-redef]
    import rules  # type: ignore[no-redef]
    import sheets  # type: ignore[no-redef]

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_CSV_BYTES = 2 * 1024 * 1024  # 2 MB batas aman upload CSV (CWE-400)


# ---------------------------------------------------------------------------
# Skema Request (Pydantic Models)
# ---------------------------------------------------------------------------
class SetupBody(BaseModel):
    username: str
    password: str


class LoginBody(BaseModel):
    username: str
    password: str
    totp: str


class SchemeBody(BaseModel):
    kode: str
    nama: str
    kategori: str = "Sertifikasi & Vokasi"
    deskripsi: str | None = None
    pass_threshold: int = 70
    predicate_sangat_mahir: int = 90
    predicate_mahir: int = 80
    predicate_cakap: int = 70
    clone_from_kode: str | None = None


class SchemePatch(BaseModel):
    nama: str | None = None
    kategori: str | None = None
    deskripsi: str | None = None
    pass_threshold: int | None = None
    predicate_sangat_mahir: int | None = None
    predicate_mahir: int | None = None
    predicate_cakap: int | None = None
    aktif: bool | None = None


class SchoolBody(BaseModel):
    nama: str
    kode: str | None = None
    scheme_kode: str | None = None
    alamat: str | None = None
    kontak: str | None = None


class SchoolPatch(BaseModel):
    nama: str | None = None
    kode: str | None = None
    scheme_kode: str | None = None
    alamat: str | None = None
    kontak: str | None = None


class ParticipantBody(BaseModel):
    nomor: str
    nama: str
    kelas: str | None = None


class ParticipantPatch(BaseModel):
    nomor: str | None = None
    nama: str | None = None
    kelas: str | None = None


class AssessmentStart(BaseModel):
    participant_id: int
    scheme_kode: str | None = None
    enrollment_id: int


class ScoreItem(BaseModel):
    indicator_kode: str
    value: int | None = None
    note: str | None = None
    client_ts: str | None = None


class SyncScoreItem(ScoreItem):
    assessment_id: int


class ScoresBody(BaseModel):
    items: list[ScoreItem]
    client_ts: str | None = None


class LockBody(BaseModel):
    confirm_empty: bool = False


class UnlockBody(BaseModel):
    reason: str = ""


class UnitBody(BaseModel):
    kode: str
    judul: str
    scheme_kode: str | None = None
    urutan: int | None = None
    aktif: bool = True


class UnitPatch(BaseModel):
    judul: str | None = None
    urutan: int | None = None
    aktif: bool | None = None


class IndicatorBody(BaseModel):
    kode: str | None = None
    teks: str
    urutan: int | None = None
    aktif: bool = True
    is_proposed: bool = False


class IndicatorPatch(BaseModel):
    teks: str | None = None
    urutan: int | None = None
    aktif: bool | None = None


class SubBody(BaseModel):
    kode: str
    judul: str
    urutan: int
    unit_kodes: list[str]
    scheme_kode: str | None = None


class SubPatch(BaseModel):
    judul: str | None = None
    urutan: int | None = None
    unit_kodes: list[str] | None = None


class SyncScoresBody(BaseModel):
    items: list[SyncScoreItem]
    client_ts: str | None = None


class SheetsBody(BaseModel):
    school_id: int | None = None
    exam_id: int | None = None


class SheetsConfigBody(BaseModel):
    spreadsheet_url_or_id: str
    service_account_json: str | None = None


# ---------------------------------------------------------------------------
# Fungsi Helper Domain
# ---------------------------------------------------------------------------
def fail(status_code: int, code: str, **extra: Any) -> None:
    raise HTTPException(status_code=status_code, detail={"error": code, **extra})


def normalize_space(value: str | None) -> str:
    return " ".join((value or "").split())


def normalize_school_name(value: str) -> str:
    return normalize_space(value).title()


def normalize_kode(value: str, fallback: str = "SEKOLAH") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "-" else "_" for ch in value.upper())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")[:60] or fallback


def unique_school_kode(conn: sqlite3.Connection, base: str) -> str:
    kode = base
    suffix = 2
    while conn.execute("SELECT 1 FROM school WHERE kode = ?", (kode,)).fetchone():
        kode = f"{base[:55]}_{suffix}"
        suffix += 1
    return kode


def participant_label(conn: sqlite3.Connection, participant_id: int) -> str:
    row = conn.execute("SELECT nama, nomor FROM participant WHERE id = ?", (participant_id,)).fetchone()
    if row is None:
        return ""
    return rules.participant_label(row["nama"], row["nomor"])


def config_for_rules(conn: sqlite3.Connection, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    config = db.all_config(conn)
    snap_thresh = (snapshot or {}).get("thresholds") or {}
    snap_templates = (snapshot or {}).get("templates")
    scheme_nama = (snapshot or {}).get("scheme_nama") or "Junior Network Technician"
    return {
        "pass_threshold": snap_thresh.get("pass_threshold", config.get("pass_threshold", 70)),
        "predicate_sangat_mahir": snap_thresh.get(
            "predicate_sangat_mahir", config.get("predicate_sangat_mahir", 90)
        ),
        "predicate_mahir": snap_thresh.get("predicate_mahir", config.get("predicate_mahir", 80)),
        "predicate_cakap": snap_thresh.get("predicate_cakap", config.get("predicate_cakap", 70)),
        "scheme_nama": scheme_nama,
        "templates": snap_templates or config.get("templates", rules.DEFAULT_CONFIG["templates"]),
    }


def scores_map(conn: sqlite3.Connection, assessment_id: int) -> dict[str, int | None]:
    return {
        row["indicator_kode"]: row["value"]
        for row in conn.execute(
            "SELECT indicator_kode, value FROM score WHERE assessment_id = ?", (assessment_id,)
        )
    }


def latest_assessment(conn: sqlite3.Connection, participant_id: int):
    return conn.execute(
        "SELECT * FROM assessment WHERE participant_id = ? ORDER BY id DESC LIMIT 1",
        (participant_id,),
    ).fetchone()


def assessment_exam_status(conn: sqlite3.Connection, assessment_id: int) -> str | None:
    row = conn.execute(
        """SELECT e.status FROM assessment a
           JOIN exam_enrollment ee ON ee.id = a.exam_enrollment_id
           JOIN exam e ON e.id = ee.exam_id
           WHERE a.id = ?""",
        (assessment_id,),
    ).fetchone()
    return row["status"] if row else None


def compute_assessment_result(conn: sqlite3.Connection, assessment) -> dict[str, Any]:
    snapshot = json.loads(assessment["instrument_json"])
    if assessment["status"] == "locked" and assessment["result_json"]:
        return json.loads(assessment["result_json"])
    label = participant_label(conn, assessment["participant_id"])
    return rules.compute_result(
        snapshot.get("units", []),
        snapshot.get("sub_competencies", []),
        scores_map(conn, assessment["id"]),
        label,
        config_for_rules(conn, snapshot),
    )


def _build_units_payload(
    snapshot: dict[str, Any],
    score_rows: dict[str, dict[str, Any]],
    unit_result_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    units_payload: list[dict[str, Any]] = []
    for unit in snapshot.get("units", []):
        indicators_payload: list[dict[str, Any]] = []
        for ind in unit.get("indicators", []):
            score = score_rows.get(ind["kode"], {})
            indicators_payload.append(
                {
                    "kode": ind["kode"],
                    "teks": ind["teks"],
                    "urutan": ind["urutan"],
                    "is_proposed": bool(ind.get("is_proposed", 0)),
                    "value": score.get("value"),
                    "note": score.get("note") or "",
                    "synced": bool(score.get("synced", 1)),
                    "client_ts": score.get("client_ts"),
                    "updated_at": score.get("updated_at"),
                }
            )
        summary = unit_result_map.get(unit["kode"], {})
        units_payload.append(
            {
                "kode": unit["kode"],
                "judul": unit["judul"],
                "urutan": unit["urutan"],
                "indicators": indicators_payload,
                "total_score": summary.get("total_score", 0),
                "max_score": summary.get("max_score", 0),
                "percent": summary.get("percent", 0.0),
                "passed": bool(summary.get("passed", False)),
                "filled": summary.get("filled", 0),
                "empty_count": summary.get("empty_count", len(indicators_payload)),
            }
        )
    return units_payload


def assessment_full(conn: sqlite3.Connection, assessment) -> dict[str, Any]:
    snapshot = json.loads(assessment["instrument_json"])
    participant = conn.execute(
        "SELECT * FROM participant WHERE id = ?", (assessment["participant_id"],)
    ).fetchone()
    school = conn.execute(
        "SELECT id, kode, nama, scheme_kode FROM school WHERE id = ?", (participant["school_id"],)
    ).fetchone()
    score_rows = {
        row["indicator_kode"]: dict(row)
        for row in conn.execute("SELECT * FROM score WHERE assessment_id = ?", (assessment["id"],))
    }
    result = compute_assessment_result(conn, assessment)
    unit_result_map = {u["kode"]: u for u in result.get("unit_results", [])}
    units_payload = _build_units_payload(snapshot, score_rows, unit_result_map)

    total_indicators = sum(len(u["indicators"]) for u in units_payload)
    filled = sum(u["filled"] for u in units_payload)
    progress = {
        "filled": filled,
        "total": total_indicators,
        "percent": round((filled / total_indicators) * 100, 2) if total_indicators else 0.0,
        "units_passed": len(result.get("unit_passed", [])),
        "units_total": len(units_payload),
        "empty_count": len(result.get("empty_indicators", [])),
    }
    cfg_rules = config_for_rules(conn, snapshot)
    scheme_kode = snapshot.get("scheme_kode") or school["scheme_kode"] or db.DEFAULT_SCHEME_KODE
    scheme_nama = snapshot.get("scheme_nama") or "Junior Network Technician"
    enrollment = (
        conn.execute(
            """SELECT ee.id, ee.exam_id, ee.group_label, ee.status AS enrollment_status,
                      e.title AS exam_title, e.year AS exam_year, e.status AS exam_status
               FROM exam_enrollment ee JOIN exam e ON e.id = ee.exam_id
               WHERE ee.id = ?""",
            (assessment["exam_enrollment_id"],),
        ).fetchone()
        if assessment["exam_enrollment_id"]
        else None
    )
    return {
        "assessment": {
            "id": assessment["id"],
            "participant_id": assessment["participant_id"],
            "enrollment_id": assessment["exam_enrollment_id"],
            "exam": dict(enrollment) if enrollment else None,
            "scheme_kode": scheme_kode,
            "scheme_nama": scheme_nama,
            "instrument_version": assessment["instrument_version"],
            "status": assessment["status"],
            "started_at": assessment["started_at"],
            "locked_at": assessment["locked_at"],
            "unlocked_at": assessment["unlocked_at"],
            "unlock_reason": assessment["unlock_reason"],
            "participant": dict(participant),
            "school": dict(school),
        },
        "units": units_payload,
        "sub_competencies": snapshot.get("sub_competencies", []),
        "progress": progress,
        "result": result,
        "locked": assessment["status"] == "locked",
        "thresholds": {
            "pass_threshold": cfg_rules["pass_threshold"],
            "predicate_sangat_mahir": cfg_rules["predicate_sangat_mahir"],
            "predicate_mahir": cfg_rules["predicate_mahir"],
            "predicate_cakap": cfg_rules["predicate_cakap"],
        },
    }


def result_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    return {
        "outcome": result.get("outcome"),
        "outcome_label": result.get("outcome_label"),
        "predicate": result.get("predicate"),
        "average_percent": result.get("average_percent"),
        "unit_passed": result.get("unit_passed", []),
        "unit_failed": result.get("unit_failed", []),
        "unit_passed_count": len(result.get("unit_passed", [])),
        "statement": result.get("statement"),
        "selected_sub": result.get("selected_sub"),
        "empty_count": result.get("empty_count", 0),
    }


def school_overview(conn: sqlite3.Connection, school) -> dict[str, Any]:
    participants = conn.execute(
        "SELECT * FROM participant WHERE school_id = ? ORDER BY nomor", (school["id"],)
    ).fetchall()
    scheme_row = conn.execute(
        "SELECT kode, nama, kategori FROM scheme WHERE kode = ?",
        (school["scheme_kode"] or db.DEFAULT_SCHEME_KODE,),
    ).fetchone()
    rows: list[dict[str, Any]] = []
    stats = {"participants": len(participants), "locked": 0, "in_progress": 0, "not_started": 0}
    for participant in participants:
        assessment = latest_assessment(conn, participant["id"])
        result = None
        progress = 0.0
        status = "not_started"
        if assessment:
            status = assessment["status"]
            result = compute_assessment_result(conn, assessment)
            snapshot = json.loads(assessment["instrument_json"])
            total = sum(len(unit.get("indicators", [])) for unit in snapshot.get("units", []))
            filled = conn.execute(
                "SELECT COUNT(*) FROM score WHERE assessment_id = ? AND value IS NOT NULL",
                (assessment["id"],),
            ).fetchone()[0]
            progress = round((filled / total) * 100, 2) if total else 0.0
        stats[status if status in stats else "not_started"] += 1
        rows.append(
            {
                "id": participant["id"],
                "nomor": participant["nomor"],
                "nama": participant["nama"],
                "kelas": participant["kelas"],
                "assessment_id": assessment["id"] if assessment else None,
                "status": status,
                "progress_percent": progress,
                "locked_at": assessment["locked_at"] if assessment else None,
                "result": result_summary(result),
            }
        )
    stats["percent_locked"] = (
        round((stats["locked"] / stats["participants"]) * 100, 2) if stats["participants"] else 0.0
    )
    school_dict = dict(school)
    school_dict["scheme_nama"] = scheme_row["nama"] if scheme_row else school["scheme_kode"]
    return {"school": school_dict, "stats": stats, "participants": rows}


def school_result_rows(
    conn: sqlite3.Connection,
    school_id: int,
    status_filter: str = "all",
    include_active: bool = False,
) -> list[dict[str, Any]]:
    school = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchone()
    participants = conn.execute(
        "SELECT * FROM participant WHERE school_id = ? ORDER BY nomor", (school_id,)
    ).fetchall()
    rows: list[dict[str, Any]] = []
    for participant in participants:
        assessment = latest_assessment(conn, participant["id"])
        if assessment is None:
            continue
        state = assessment["status"]
        if status_filter != "all" and state != status_filter:
            continue
        if not include_active:
            exam_status = assessment_exam_status(conn, assessment["id"])
            if state != "locked" or exam_status not in {None, "archived"}:
                continue
        result = compute_assessment_result(conn, assessment)
        rows.append(
            {
                "school_nama": school["nama"] if school else "",
                "scheme_kode": school["scheme_kode"] if school else db.DEFAULT_SCHEME_KODE,
                "participant": dict(participant),
                "assessment_id": assessment["id"],
                "status": state,
                "locked_at": assessment["locked_at"],
                "instrument_version": assessment["instrument_version"],
                "result": result,
            }
        )
    return rows


def touch_config(
    conn: sqlite3.Connection,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: Any,
    old_value: Any = None,
    new_value: Any = None,
    bump: bool = True,
    scheme_kode: str | None = None,
) -> int | None:
    version = db.bump_instrument_version(conn, scheme_kode) if bump else None
    db.audit(conn, user_id, action, entity_type, entity_id, old_value, new_value)
    return version


def indicator_next_code(conn: sqlite3.Connection, prefix: str = "IND") -> str:
    rows = conn.execute("SELECT kode FROM indicator WHERE kode LIKE ?", (f"{prefix}-%",)).fetchall()
    highest = 0
    for row in rows:
        try:
            highest = max(highest, int(row["kode"].split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{highest + 1:03d}"


def parse_csv(raw: bytes) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    if len(raw) > MAX_CSV_BYTES:
        fail(413, "csv_too_large", message="Ukuran file CSV maksimal 2 MB")
    text = raw.decode("utf-8-sig", errors="replace")
    if not text.strip():
        fail(400, "empty_csv")
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        fail(400, "invalid_header", required=["nomor", "nama"])
    original = list(reader.fieldnames)
    normalized = {name: name.strip().lower() for name in original}
    present = set(normalized.values())
    if not {"nomor", "nama"}.issubset(present):
        fail(400, "invalid_header", required=["nomor", "nama"], found=sorted(present))

    valid: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        values = {
            normalized[name]: normalize_space(row.get(name) or "")
            for name in original
            if name in normalized
        }
        nomor = values.get("nomor", "")
        nama = values.get("nama", "")
        kelas = values.get("kelas", "")
        if not nomor and not nama and not kelas:
            continue
        if not nomor:
            errors.append({"row": row_number, "field": "nomor", "message": "Nomor peserta wajib diisi"})
            continue
        if not nama:
            errors.append({"row": row_number, "field": "nama", "message": "Nama wajib diisi"})
            continue
        if nomor in seen:
            duplicates.append({"row": row_number, "nomor": nomor, "reason": "duplikat dalam file"})
            continue
        seen.add(nomor)
        valid.append({"nomor": nomor, "nama": nama, "kelas": kelas})
    return valid, errors, duplicates


def _enrich_scheme(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    kode = row["kode"]
    unit_count = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE scheme_kode = ? AND aktif = 1", (kode,)
    ).fetchone()[0]
    ind_count = conn.execute(
        """
        SELECT COUNT(*) FROM indicator i
        JOIN unit u ON u.kode = i.unit_kode
        WHERE u.scheme_kode = ? AND u.aktif = 1 AND i.aktif = 1
        """,
        (kode,),
    ).fetchone()[0]
    sub_count = conn.execute(
        "SELECT COUNT(*) FROM sub_competency WHERE scheme_kode = ?", (kode,)
    ).fetchone()[0]
    school_count = conn.execute(
        "SELECT COUNT(*) FROM school WHERE scheme_kode = ?", (kode,)
    ).fetchone()[0]
    participant_count = conn.execute(
        """
        SELECT COUNT(*) FROM participant p
        JOIN school s ON s.id = p.school_id
        WHERE s.scheme_kode = ?
        """,
        (kode,),
    ).fetchone()[0]
    item = dict(row)
    item.update(
        {
            "units_count": unit_count,
            "indicators_count": ind_count,
            "sub_competencies_count": sub_count,
            "schools_count": school_count,
            "participants_count": participant_count,
        }
    )
    return item


# ---------------------------------------------------------------------------
# Registrasi Route Modular
# ---------------------------------------------------------------------------
def _register_auth_routes(app: FastAPI, db_dep: Any, auth_ctx: Any) -> None:
    @app.get("/api/auth/status")
    def auth_status(request: Request, conn: sqlite3.Connection = Depends(db_dep)):
        user_count = conn.execute("SELECT COUNT(*) FROM user").fetchone()[0]
        user = auth.get_session_user(conn, request.cookies.get(auth.COOKIE_NAME))
        return {"needs_setup": user_count == 0, "authenticated": user is not None, "user": user}

    @app.post("/api/auth/setup")
    def auth_setup(body: SetupBody, conn: sqlite3.Connection = Depends(db_dep)):
        if conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] > 0:
            fail(409, "already_setup")
        username = normalize_space(body.username)
        if len(username) < 3:
            fail(400, "invalid_username", message="Username minimal 3 karakter")
        if len(body.password) < 8:
            fail(400, "weak_password", message="Password minimal 8 karakter")
        secret = auth.new_totp_secret()
        cur = conn.execute(
            "INSERT INTO user (username, password_hash, totp_secret, created_at) VALUES (?, ?, ?, ?)",
            (username, auth.hash_password(body.password), secret, db.utcnow()),
        )
        db.audit(conn, cur.lastrowid, "setup", "user", cur.lastrowid, new_value={"username": username})
        conn.commit()
        return {"username": username, "secret": secret, "otpauth_uri": auth.totp_uri(secret, username)}

    @app.post("/api/auth/login")
    def auth_login(
        body: LoginBody, request: Request, response: Response, conn: sqlite3.Connection = Depends(db_dep)
    ):
        ip = auth.client_ip(request)
        limiter: auth.LoginRateLimiter = app.state.rate_limiter
        if not limiter.check(ip):
            fail(429, "rate_limited", message="Terlalu banyak percobaan. Coba lagi dalam 1 menit.")
        limiter.hit(ip)
        user = conn.execute(
            "SELECT * FROM user WHERE lower(username) = lower(?)", (normalize_space(body.username),)
        ).fetchone()
        if user is None or not auth.verify_password(body.password, user["password_hash"]):
            fail(401, "invalid_credentials")
        if not auth.verify_totp(user["totp_secret"], body.totp):
            fail(401, "invalid_credentials")
        token = auth.create_session(conn, user["id"])
        response.set_cookie(
            key=auth.COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="strict",
            secure=auth.cookie_secure(request),
            max_age=auth.session_days() * 86400,
            path="/",
        )
        db.audit(conn, user["id"], "login", "user", user["id"], metadata={"ip": ip})
        conn.commit()
        return {"ok": True, "user": {"id": user["id"], "username": user["username"], "totp_enabled": True}}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(db_dep)):
        auth.delete_session(conn, request.cookies.get(auth.COOKIE_NAME))
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def auth_me(ctx: tuple = Depends(auth_ctx)):
        _, user = ctx
        return {"user": user}


def _register_scheme_and_recap_routes(app: FastAPI, auth_ctx: Any) -> None:
    @app.get("/api/schemes")
    def list_schemes(ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        rows = conn.execute("SELECT * FROM scheme ORDER BY created_at, kode").fetchall()
        data = [_enrich_scheme(conn, row) for row in rows]
        return {"data": data, "meta": {"total": len(data)}}

    @app.post("/api/schemes", status_code=201)
    def create_scheme(body: SchemeBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        kode = normalize_kode(body.kode, "SKEMA")
        nama = normalize_space(body.nama)
        if len(nama) < 3:
            fail(400, "invalid_nama", message="Nama skema minimal 3 karakter")
        if conn.execute("SELECT 1 FROM scheme WHERE kode = ?", (kode,)).fetchone():
            fail(409, "scheme_exists")
        templates = {
            "penuh": f"Peserta {{peserta}} dinyatakan kompeten sebagai {nama} dengan predikat {{predikat}}.",
            "sub": "Peserta {peserta} dinyatakan kompeten pada sub kompetensi {sub} dengan predikat {predikat}.",
            "unit": "Peserta {peserta} dinyatakan kompeten pada unit {unit} dengan predikat {predikat}.",
            "belum": "Peserta {peserta} dinyatakan belum kompeten.",
        }
        now = db.utcnow()
        conn.execute(
            """
            INSERT INTO scheme
                (kode, nama, kategori, deskripsi, pass_threshold,
                 predicate_sangat_mahir, predicate_mahir, predicate_cakap,
                 templates_json, aktif, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (
                kode,
                nama,
                normalize_space(body.kategori) or "Sertifikasi & Vokasi",
                normalize_space(body.deskripsi),
                body.pass_threshold,
                body.predicate_sangat_mahir,
                body.predicate_mahir,
                body.predicate_cakap,
                json.dumps(templates, ensure_ascii=False),
                now,
                now,
            ),
        )
        db.audit(conn, user["id"], "scheme_create", "scheme", kode, new_value={"kode": kode, "nama": nama})
        conn.commit()
        row = conn.execute("SELECT * FROM scheme WHERE kode = ?", (kode,)).fetchone()
        return _enrich_scheme(conn, row)

    @app.get("/api/schemes/{scheme_kode}")
    def get_scheme(scheme_kode: str, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        row = conn.execute("SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        if row is None:
            fail(404, "scheme_not_found")
        return _enrich_scheme(conn, row)

    @app.patch("/api/schemes/{scheme_kode}")
    def patch_scheme(scheme_kode: str, body: SchemePatch, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        if row is None:
            fail(404, "scheme_not_found")
        changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if "nama" in changes:
            changes["nama"] = normalize_space(changes["nama"])
        if "kategori" in changes:
            changes["kategori"] = normalize_space(changes["kategori"])
        if "deskripsi" in changes:
            changes["deskripsi"] = normalize_space(changes["deskripsi"])
        if "aktif" in changes:
            changes["aktif"] = 1 if changes["aktif"] else 0
        if changes:
            fields = ", ".join(f"{k} = ?" for k in changes)
            conn.execute(
                f"UPDATE scheme SET {fields}, updated_at = ? WHERE kode = ?",
                [*changes.values(), db.utcnow(), scheme_kode],
            )
            db.audit(conn, user["id"], "scheme_update", "scheme", scheme_kode, dict(row), changes)
            conn.commit()
        updated = conn.execute("SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        return _enrich_scheme(conn, updated)

    @app.delete("/api/schemes/{scheme_kode}")
    def delete_scheme(scheme_kode: str, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        if scheme_kode == db.DEFAULT_SCHEME_KODE:
            fail(400, "cannot_delete_default_scheme")
        row = conn.execute("SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        if row is None:
            fail(404, "scheme_not_found")
        used = conn.execute("SELECT COUNT(*) FROM school WHERE scheme_kode = ?", (scheme_kode,)).fetchone()[0]
        if used:
            fail(409, "scheme_has_schools")
        conn.execute("DELETE FROM scheme WHERE kode = ?", (scheme_kode,))
        db.audit(conn, user["id"], "scheme_delete", "scheme", scheme_kode, old_value=dict(row))
        conn.commit()
        return {"ok": True}

    @app.get("/api/recap/summary")
    def recap_summary(
        scheme_kode: str | None = None,
        school_id: int | None = None,
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        return recap.compute_recap_summary(conn, compute_assessment_result, scheme_kode, school_id)

    @app.get("/api/schemes/{scheme_kode}/export")
    def export_scheme_results(scheme_kode: str, format: str = "xlsx", ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        scheme = conn.execute("SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        if scheme is None:
            fail(404, "scheme_not_found")
        if format not in {"csv", "xlsx"}:
            fail(400, "invalid_format")
        schools = conn.execute(
            "SELECT * FROM school WHERE scheme_kode = ? ORDER BY nama", (scheme_kode,)
        ).fetchall()
        all_rows: list[dict[str, Any]] = []
        for s in schools:
            all_rows.extend(school_result_rows(conn, s["id"], "all", include_active=True))
        snapshot = db.get_snapshot(conn, scheme_kode)
        units = snapshot.get("units", [])
        stamp = date.today().strftime("%Y%m%d")
        safe_kode = normalize_kode(scheme_kode).lower()
        if format == "csv":
            return recap.build_export_csv(all_rows, units, safe_kode, stamp, include_school=True)
        return recap.build_export_xlsx(all_rows, units, safe_kode, stamp, include_school=True)


def _school_stats(conn: sqlite3.Connection, school_id: int) -> dict[str, int]:
    total = conn.execute("SELECT COUNT(*) FROM participant WHERE school_id = ?", (school_id,)).fetchone()[0]
    locked = conn.execute(
        """
        SELECT COUNT(*) FROM participant p
        JOIN assessment a ON a.id = (
            SELECT id FROM assessment WHERE participant_id = p.id ORDER BY id DESC LIMIT 1
        )
        WHERE p.school_id = ? AND a.status = 'locked'
        """,
        (school_id,),
    ).fetchone()[0]
    in_progress = conn.execute(
        """
        SELECT COUNT(*) FROM participant p
        JOIN assessment a ON a.id = (
            SELECT id FROM assessment WHERE participant_id = p.id ORDER BY id DESC LIMIT 1
        )
        WHERE p.school_id = ? AND a.status = 'in_progress'
        """,
        (school_id,),
    ).fetchone()[0]
    return {
        "participant_count": total,
        "locked_count": locked,
        "in_progress_count": in_progress,
        "not_started_count": max(0, total - locked - in_progress),
    }


def _enrich_school(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    scheme_kode = item.get("scheme_kode") or db.DEFAULT_SCHEME_KODE
    scheme_row = conn.execute("SELECT nama FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
    item["scheme_kode"] = scheme_kode
    item["scheme_nama"] = scheme_row["nama"] if scheme_row else scheme_kode
    item.update(_school_stats(conn, row["id"]))
    return item


def _register_school_routes(app: FastAPI, auth_ctx: Any) -> None:
    @app.get("/api/schools")
    def list_schools(scheme_kode: str | None = None, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        if scheme_kode and scheme_kode != "all":
            rows = conn.execute(
                "SELECT * FROM school WHERE scheme_kode = ? ORDER BY nama", (scheme_kode,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM school ORDER BY nama").fetchall()
        data = [_enrich_school(conn, row) for row in rows]
        return {"data": data, "meta": {"total": len(data)}}

    @app.post("/api/schools", status_code=201)
    def create_school(body: SchoolBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        nama = normalize_school_name(body.nama)
        if len(nama) < 2:
            fail(400, "invalid_nama", message="Nama sekolah minimal 2 karakter")
        scheme_kode = (body.scheme_kode or db.DEFAULT_SCHEME_KODE).strip()
        if conn.execute("SELECT 1 FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone() is None:
            fail(400, "scheme_not_found", scheme_kode=scheme_kode)
        nama_norm = nama.lower().replace("  ", " ")
        existing = conn.execute(
            "SELECT id FROM school WHERE lower(replace(nama, '  ', ' ')) = ?", (nama_norm,)
        ).fetchone()
        if existing:
            fail(409, "nama_exists", existing_id=existing["id"])
        base_kode = normalize_kode(body.kode or nama)
        if body.kode:
            kode = base_kode
            if conn.execute("SELECT 1 FROM school WHERE kode = ?", (kode,)).fetchone():
                fail(409, "kode_exists")
        else:
            kode = unique_school_kode(conn, base_kode)
        now = db.utcnow()
        cur = conn.execute(
            """
            INSERT INTO school (kode, nama, scheme_kode, alamat, kontak, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (kode, nama, scheme_kode, normalize_space(body.alamat), normalize_space(body.kontak), now, now),
        )
        db.audit(
            conn,
            user["id"],
            "school_create",
            "school",
            cur.lastrowid,
            new_value={"kode": kode, "nama": nama, "scheme_kode": scheme_kode},
        )
        conn.commit()
        row = conn.execute("SELECT * FROM school WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _enrich_school(conn, row)

    @app.get("/api/schools/{school_id}")
    def get_school(school_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        row = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchone()
        if row is None:
            fail(404, "school_not_found")
        return _enrich_school(conn, row)

    @app.patch("/api/schools/{school_id}")
    def patch_school(school_id: int, body: SchoolPatch, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchone()
        if row is None:
            fail(404, "school_not_found")
        changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if "nama" in changes:
            changes["nama"] = normalize_school_name(changes["nama"])
            if len(changes["nama"]) < 2:
                fail(400, "invalid_nama")
            nama_norm = changes["nama"].lower().replace("  ", " ")
            existing = conn.execute(
                "SELECT id FROM school WHERE lower(replace(nama, '  ', ' ')) = ? AND id != ?",
                (nama_norm, school_id),
            ).fetchone()
            if existing:
                fail(409, "nama_exists", existing_id=existing["id"])
        if "kode" in changes:
            kode = normalize_kode(changes["kode"])
            if kode != row["kode"] and conn.execute(
                "SELECT 1 FROM school WHERE kode = ? AND id != ?", (kode, school_id)
            ).fetchone():
                fail(409, "kode_exists")
            changes["kode"] = kode
        if "scheme_kode" in changes:
            if conn.execute("SELECT 1 FROM scheme WHERE kode = ?", (changes["scheme_kode"],)).fetchone() is None:
                fail(400, "scheme_not_found")
        if changes:
            fields = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE school SET {fields}, updated_at = ? WHERE id = ?",
                [*changes.values(), db.utcnow(), school_id],
            )
            db.audit(conn, user["id"], "school_update", "school", school_id, dict(row), changes)
            conn.commit()
        return get_school(school_id, (conn, user))

    @app.delete("/api/schools/{school_id}")
    def delete_school(school_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchone()
        if row is None:
            fail(404, "school_not_found")
        if conn.execute("SELECT COUNT(*) FROM participant WHERE school_id = ?", (school_id,)).fetchone()[0]:
            fail(409, "school_has_participants")
        conn.execute("DELETE FROM school WHERE id = ?", (school_id,))
        db.audit(conn, user["id"], "school_delete", "school", school_id, old_value=dict(row))
        conn.commit()
        return {"ok": True}

    _register_participant_and_result_routes(app, auth_ctx)


def _register_participant_and_result_routes(app: FastAPI, auth_ctx: Any) -> None:
    @app.get("/api/schools/{school_id}/participants")
    def list_participants(
        school_id: int,
        exam_id: int | None = None,
        group_label: str | None = None,
        enrollment_status: str | None = None,
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        if conn.execute("SELECT 1 FROM school WHERE id=?", (school_id,)).fetchone() is None:
            fail(404, "school_not_found")
        if exam_id is not None:
            exam = conn.execute("SELECT id FROM exam WHERE id=?", (exam_id,)).fetchone()
            if exam is None or conn.execute(
                "SELECT 1 FROM exam_school WHERE exam_id=? AND school_id=?",
                (exam_id, school_id),
            ).fetchone() is None:
                fail(404, "exam_school_not_found")
            clauses = ["ee.exam_id=?", "ee.school_id=?"]
            values: list[Any] = [exam_id, school_id]
            if group_label:
                clauses.append("ee.group_label=?")
                values.append(normalize_space(group_label))
            if enrollment_status:
                if enrollment_status not in {"enrolled", "withdrawn"}:
                    fail(400, "invalid_enrollment_status")
                clauses.append("ee.status=?")
                values.append(enrollment_status)
            rows = conn.execute(
                f"""SELECT ee.id AS enrollment_id, ee.participant_id, ee.exam_id, ee.school_id,
                           ee.scheme_kode, ee.group_label, ee.snapshot_number AS nomor,
                           ee.snapshot_name AS nama, ee.snapshot_class AS kelas,
                           ee.status AS enrollment_status, a.id AS assessment_id,
                           a.status AS assessment_status, a.locked_at, a.result_json
                    FROM exam_enrollment ee
                    LEFT JOIN assessment a ON a.exam_enrollment_id=ee.id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY ee.group_label, ee.snapshot_number, ee.id""",
                values,
            ).fetchall()
            data = []
            for row in rows:
                item = dict(row)
                item["result"] = json.loads(row["result_json"]) if row["result_json"] else None
                item.pop("result_json", None)
                data.append(item)
            return {"data": data, "meta": {"total": len(data), "exam_id": exam_id}}
        rows = conn.execute(
            "SELECT * FROM participant WHERE school_id = ? ORDER BY nomor", (school_id,)
        ).fetchall()
        return {"data": [dict(row) for row in rows], "meta": {"total": len(rows)}}

    @app.post("/api/schools/{school_id}/participants", status_code=201)
    def create_participant(school_id: int, body: ParticipantBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        if conn.execute("SELECT 1 FROM school WHERE id = ?", (school_id,)).fetchone() is None:
            fail(404, "school_not_found")
        nomor = normalize_space(body.nomor)
        nama = normalize_space(body.nama)
        if not nomor or not nama:
            fail(400, "invalid_participant", message="Nomor dan nama wajib diisi")
        if conn.execute(
            "SELECT 1 FROM participant WHERE school_id = ? AND nomor = ?", (school_id, nomor)
        ).fetchone():
            fail(409, "nomor_exists")
        now = db.utcnow()
        cur = conn.execute(
            """
            INSERT INTO participant (school_id, nomor, nama, kelas, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (school_id, nomor, nama, normalize_space(body.kelas), now, now),
        )
        db.audit(
            conn,
            user["id"],
            "participant_create",
            "participant",
            cur.lastrowid,
            new_value={"nomor": nomor, "nama": nama},
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM participant WHERE id = ?", (cur.lastrowid,)).fetchone())

    @app.patch("/api/schools/{school_id}/participants/{participant_id}")
    def patch_participant(
        school_id: int, participant_id: int, body: ParticipantPatch, ctx: tuple = Depends(auth_ctx)
    ):
        conn, user = ctx
        row = conn.execute(
            "SELECT * FROM participant WHERE id = ? AND school_id = ?", (participant_id, school_id)
        ).fetchone()
        if row is None:
            fail(404, "participant_not_found")
        changes = {k: normalize_space(v) for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if "nomor" in changes:
            if not changes["nomor"]:
                fail(400, "invalid_nomor")
            if conn.execute(
                "SELECT 1 FROM participant WHERE school_id = ? AND nomor = ? AND id != ?",
                (school_id, changes["nomor"], participant_id),
            ).fetchone():
                fail(409, "nomor_exists")
        if changes:
            fields = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE participant SET {fields}, updated_at = ? WHERE id = ?",
                [*changes.values(), db.utcnow(), participant_id],
            )
            db.audit(conn, user["id"], "participant_update", "participant", participant_id, dict(row), changes)
            conn.commit()
        return dict(conn.execute("SELECT * FROM participant WHERE id = ?", (participant_id,)).fetchone())

    @app.delete("/api/schools/{school_id}/participants/{participant_id}")
    def delete_participant(school_id: int, participant_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute(
            "SELECT * FROM participant WHERE id = ? AND school_id = ?", (participant_id, school_id)
        ).fetchone()
        if row is None:
            fail(404, "participant_not_found")
        if conn.execute(
            "SELECT 1 FROM exam_enrollment WHERE participant_id = ? LIMIT 1", (participant_id,)
        ).fetchone():
            fail(409, "participant_has_exam_history")
        if latest_assessment(conn, participant_id) is not None:
            fail(409, "participant_has_assessment")
        conn.execute("DELETE FROM participant WHERE id = ?", (participant_id,))
        db.audit(conn, user["id"], "participant_delete", "participant", participant_id, old_value=dict(row))
        conn.commit()
        return {"ok": True}

    @app.post("/api/schools/{school_id}/participants/import")
    def import_participants(school_id: int, file: UploadFile = File(...), ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        if conn.execute("SELECT 1 FROM school WHERE id = ?", (school_id,)).fetchone() is None:
            fail(404, "school_not_found")
        raw = file.file.read(MAX_CSV_BYTES + 1)
        valid, errors, duplicates = parse_csv(raw)
        imported = 0
        now = db.utcnow()
        for item in valid:
            if conn.execute(
                "SELECT 1 FROM participant WHERE school_id = ? AND nomor = ?", (school_id, item["nomor"])
            ).fetchone():
                duplicates.append({"row": None, "nomor": item["nomor"], "reason": "sudah terdaftar"})
                continue
            cur = conn.execute(
                """
                INSERT INTO participant (school_id, nomor, nama, kelas, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (school_id, item["nomor"], item["nama"], item["kelas"], now, now),
            )
            imported += 1
            db.audit(conn, user["id"], "participant_import", "participant", cur.lastrowid, new_value=item)
        conn.commit()
        return {
            "imported": imported,
            "errors": errors,
            "duplicates": duplicates,
            "total_rows": len(valid) + len(errors) + len(duplicates),
        }

    @app.get("/api/schools/{school_id}/overview")
    def overview(school_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        row = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchone()
        if row is None:
            fail(404, "school_not_found")
        return school_overview(conn, row)

    @app.get("/api/schools/{school_id}/results")
    def school_results(school_id: int, status: str = "all", ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        school = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchone()
        if school is None:
            fail(404, "school_not_found")
        if status not in {"all", "locked", "in_progress"}:
            fail(400, "invalid_status")
        rows = school_result_rows(conn, school_id, status)
        return {
            "school": _enrich_school(conn, school),
            "generated_at": db.utcnow(),
            "data": rows,
            "meta": {"total": len(rows)},
        }

    @app.get("/api/schools/{school_id}/export")
    def export_results(school_id: int, format: str = "csv", ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        school = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchone()
        if school is None:
            fail(404, "school_not_found")
        if format not in {"csv", "xlsx"}:
            fail(400, "invalid_format")
        rows = school_result_rows(conn, school_id, "all", include_active=True)
        scheme_kode = school["scheme_kode"] or db.DEFAULT_SCHEME_KODE
        snapshot = db.get_snapshot(conn, scheme_kode)
        units = snapshot.get("units", [])
        stamp = date.today().strftime("%Y%m%d")
        safe_kode = normalize_kode(school["kode"]).lower() or "sekolah"
        if format == "csv":
            return recap.build_export_csv(rows, units, safe_kode, stamp)
        return recap.build_export_xlsx(rows, units, safe_kode, stamp)


def apply_score_item(
    conn: sqlite3.Connection,
    assessment: Any,
    item: ScoreItem,
    user_id: int,
    fallback_ts: str | None = None,
) -> str:
    """Terapkan satu skor indikator. Kembalikan 'synced', 'skipped', atau kode error."""
    if assessment_exam_status(conn, assessment["id"]) == "archived":
        return "exam_archived"
    if assessment["status"] == "locked":
        return "assessment_locked"
    snapshot = json.loads(assessment["instrument_json"])
    valid = {ind["kode"] for unit in snapshot.get("units", []) for ind in unit.get("indicators", [])}
    if item.indicator_kode not in valid:
        return "indicator_not_in_assessment"
    if item.value is not None and (not isinstance(item.value, int) or item.value < 0 or item.value > 3):
        return "invalid_score"
    client_ts = item.client_ts or fallback_ts
    existing = conn.execute(
        "SELECT * FROM score WHERE assessment_id = ? AND indicator_kode = ?",
        (assessment["id"], item.indicator_kode),
    ).fetchone()
    if existing is None:
        return "score_not_found"
    if client_ts and existing["client_ts"] and client_ts < existing["client_ts"]:
        return "skipped"
    now = db.utcnow()
    old = {"value": existing["value"], "note": existing["note"]}
    note = item.note if item.note is not None else existing["note"]
    conn.execute(
        """
        UPDATE score SET value = ?, note = ?, synced = 1, client_ts = ?, updated_at = ?
        WHERE assessment_id = ? AND indicator_kode = ?
        """,
        (item.value, note, client_ts, now, assessment["id"], item.indicator_kode),
    )
    db.audit(
        conn,
        user_id,
        "score_upsert",
        "score",
        f"{assessment['id']}:{item.indicator_kode}",
        old,
        {"value": item.value, "note": note, "client_ts": client_ts},
    )
    db.record_outbox(
        conn,
        "score",
        f"score:{assessment['id']}:{item.indicator_kode}",
        {
            "assessment_id": assessment["id"],
            "indicator_kode": item.indicator_kode,
            "value": item.value,
            "note": note,
            "client_ts": client_ts,
        },
    )
    return "synced"


def _register_assessment_routes(app: FastAPI, auth_ctx: Any) -> None:
    @app.post("/api/assessments", status_code=201)
    def start_assessment(body: AssessmentStart, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        participant = conn.execute(
            "SELECT * FROM participant WHERE id = ?", (body.participant_id,)
        ).fetchone()
        if participant is None:
            fail(404, "participant_not_found")
        enrollment = conn.execute(
            """SELECT ee.*, e.status AS exam_status FROM exam_enrollment ee
               JOIN exam e ON e.id=ee.exam_id WHERE ee.id=?""",
            (body.enrollment_id,),
        ).fetchone()
        if enrollment is None or enrollment["participant_id"] != body.participant_id:
            fail(400, "enrollment_participant_mismatch")
        if enrollment["status"] != "enrolled":
            fail(409, "enrollment_not_active")
        if body.scheme_kode and body.scheme_kode != enrollment["scheme_kode"]:
            fail(400, "enrollment_scheme_mismatch")
        existing = conn.execute(
            "SELECT * FROM assessment WHERE exam_enrollment_id = ?", (body.enrollment_id,)
        ).fetchone()
        if existing is not None:
            return assessment_full(conn, existing)
        if enrollment["exam_status"] != "active":
            fail(409, "exam_not_active", status=enrollment["exam_status"])
        scheme_kode = enrollment["scheme_kode"]
        snapshot = db.get_snapshot(conn, scheme_kode)
        version = int(snapshot.get("version", db.instrument_version(conn, scheme_kode)))
        now = db.utcnow()
        cur = conn.execute(
            """
            INSERT INTO assessment
                (participant_id, scheme_kode, exam_enrollment_id, instrument_version, instrument_json, status, started_at,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?, ?)
            """,
            (
                body.participant_id,
                scheme_kode,
                body.enrollment_id,
                version,
                json.dumps(snapshot, ensure_ascii=False),
                now,
                now,
                now,
            ),
        )
        assessment_id = cur.lastrowid
        for unit in snapshot.get("units", []):
            for ind in unit.get("indicators", []):
                conn.execute(
                    """
                    INSERT INTO score
                        (assessment_id, indicator_kode, value, note, synced, created_at, updated_at)
                    VALUES (?, ?, NULL, '', 1, ?, ?)
                    """,
                    (assessment_id, ind["kode"], now, now),
                )
        db.audit(
            conn,
            user["id"],
            "assessment_start",
            "assessment",
            assessment_id,
            new_value={"participant_id": body.participant_id, "scheme_kode": scheme_kode, "enrollment_id": body.enrollment_id, "version": version},
        )
        conn.commit()
        row = conn.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,)).fetchone()
        return assessment_full(conn, row)

    @app.get("/api/assessments/{assessment_id}")
    def get_assessment(assessment_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        row = conn.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,)).fetchone()
        if row is None:
            fail(404, "assessment_not_found")
        return assessment_full(conn, row)

    @app.patch("/api/assessments/{assessment_id}/scores")
    def patch_scores(assessment_id: int, body: ScoresBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        assessment = conn.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None:
            fail(404, "assessment_not_found")
        if assessment_exam_status(conn, assessment_id) == "archived":
            fail(409, "exam_archived")
        if assessment["status"] == "locked":
            fail(409, "assessment_locked")
        snapshot = json.loads(assessment["instrument_json"])
        valid_codes = {
            ind["kode"] for unit in snapshot.get("units", []) for ind in unit.get("indicators", [])
        }
        for item in body.items:
            if item.indicator_kode not in valid_codes:
                fail(400, "indicator_not_in_assessment", indicator_kode=item.indicator_kode)
            if item.value is not None and (not isinstance(item.value, int) or item.value < 0 or item.value > 3):
                fail(400, "invalid_score", indicator_kode=item.indicator_kode)
        result_counts = {"synced": 0, "skipped": 0, "failed": 0}
        for item in body.items:
            status = apply_score_item(conn, assessment, item, user["id"], body.client_ts)
            result_counts[status if status in result_counts else "failed"] += 1
        db.set_config(conn, "last_scores_sync", db.utcnow())
        conn.commit()
        result = compute_assessment_result(conn, assessment)
        return {
            **result_counts,
            "result": result,
            "progress": {
                "empty_count": len(result.get("empty_indicators", [])),
                "total": result.get("max_score", 0) // 3 if result.get("max_score") else 0,
            },
        }

    @app.post("/api/assessments/{assessment_id}/lock")
    def lock_assessment(assessment_id: int, body: LockBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        assessment = conn.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None:
            fail(404, "assessment_not_found")
        if assessment_exam_status(conn, assessment_id) == "archived":
            fail(409, "exam_archived")
        result = compute_assessment_result(conn, assessment)
        if assessment["status"] == "locked":
            return {"status": "locked", "locked_at": assessment["locked_at"], "result": result}
        empty = result.get("empty_indicators", [])
        if empty and not body.confirm_empty:
            fail(
                400,
                "empty_indicators",
                empty_indicators=empty,
                count=len(empty),
                message="Isi semua indikator atau kirim confirm_empty=true",
            )
        now = db.utcnow()
        conn.execute(
            """
            UPDATE assessment SET status = 'locked', locked_at = ?, locked_by = ?,
                result_json = ?, updated_at = ? WHERE id = ?
            """,
            (now, user["id"], json.dumps(result, ensure_ascii=False), now, assessment_id),
        )
        db.audit(
            conn,
            user["id"],
            "assessment_lock",
            "assessment",
            assessment_id,
            new_value={"status": "locked", "confirm_empty": body.confirm_empty, "empty_count": len(empty)},
        )
        conn.commit()
        return {"status": "locked", "locked_at": now, "result": result}

    @app.post("/api/assessments/{assessment_id}/unlock")
    def unlock_assessment(assessment_id: int, body: UnlockBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        assessment = conn.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None:
            fail(404, "assessment_not_found")
        if assessment_exam_status(conn, assessment_id) == "archived":
            fail(409, "exam_archived")
        if assessment["status"] != "locked":
            fail(400, "assessment_not_locked")
        reason = body.reason.strip()
        if len(reason) < 10:
            fail(400, "reason_required", message="Alasan minimal 10 karakter")
        now = db.utcnow()
        conn.execute(
            """
            UPDATE assessment SET status = 'in_progress', result_json = NULL,
                unlocked_at = ?, unlocked_by = ?, unlock_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, user["id"], reason, now, assessment_id),
        )
        db.audit(conn, user["id"], "assessment_unlock", "assessment", assessment_id, new_value={"reason": reason})
        conn.commit()
        return {"status": "in_progress", "unlocked_at": now, "unlock_reason": reason}

    @app.get("/api/assessments/{assessment_id}/result")
    def assessment_result(assessment_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        assessment = conn.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,)).fetchone()
        if assessment is None:
            fail(404, "assessment_not_found")
        result = compute_assessment_result(conn, assessment)
        return {"locked": assessment["status"] == "locked", "locked_at": assessment["locked_at"], "result": result}


def _register_config_routes(app: FastAPI, auth_ctx: Any) -> None:
    @app.get("/api/config/instrument")
    def get_instrument_config(scheme_kode: str = db.DEFAULT_SCHEME_KODE, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        scheme_row = conn.execute("SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        if scheme_row is None:
            scheme_kode = db.DEFAULT_SCHEME_KODE
            scheme_row = conn.execute("SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        unit_count = conn.execute(
            "SELECT COUNT(*) FROM unit WHERE scheme_kode = ? AND aktif = 1", (scheme_kode,)
        ).fetchone()[0]
        indicator_count = conn.execute(
            """
            SELECT COUNT(*) FROM indicator i
            JOIN unit u ON u.kode = i.unit_kode
            WHERE u.scheme_kode = ? AND u.aktif = 1 AND i.aktif = 1
            """,
            (scheme_kode,),
        ).fetchone()[0]
        sub_count = conn.execute(
            "SELECT COUNT(*) FROM sub_competency WHERE scheme_kode = ?", (scheme_kode,)
        ).fetchone()[0]
        proposed = conn.execute(
            """
            SELECT i.kode, i.teks, i.unit_kode FROM indicator i
            JOIN unit u ON u.kode = i.unit_kode
            WHERE u.scheme_kode = ? AND i.is_proposed = 1
            ORDER BY i.kode
            """,
            (scheme_kode,),
        ).fetchall()
        config = db.all_config(conn)
        return {
            "scheme_kode": scheme_kode,
            "scheme_nama": scheme_row["nama"] if scheme_row else scheme_kode,
            "version": db.instrument_version(conn, scheme_kode),
            "units_count": unit_count,
            "indicators_count": indicator_count,
            "sub_competencies_count": sub_count,
            "updated_at": scheme_row["updated_at"] if scheme_row else config.get("instrument_updated_at"),
            "thresholds": {
                "pass_threshold": scheme_row["pass_threshold"] if scheme_row else 70,
                "predicate_sangat_mahir": scheme_row["predicate_sangat_mahir"] if scheme_row else 90,
                "predicate_mahir": scheme_row["predicate_mahir"] if scheme_row else 80,
                "predicate_cakap": scheme_row["predicate_cakap"] if scheme_row else 70,
            },
            "proposed_count": len(proposed),
            "proposed_indicators": [dict(row) for row in proposed],
            "note": (
                "Instrumen mendukung multi-skema. Setiap perubahan menaikkan versi instrumen "
                "dan assessment baru otomatis memakai snapshot skema terkait."
            ),
        }

    @app.get("/api/config/units")
    def list_units(scheme_kode: str = db.DEFAULT_SCHEME_KODE, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        units = []
        for unit in conn.execute(
            "SELECT * FROM unit WHERE scheme_kode = ? ORDER BY urutan", (scheme_kode,)
        ).fetchall():
            indicators = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM indicator WHERE unit_kode = ? ORDER BY urutan", (unit["kode"],)
                )
            ]
            item = dict(unit)
            item["indicators"] = indicators
            item["indicator_count"] = len([i for i in indicators if i["aktif"]])
            item["max_score"] = 3 * item["indicator_count"]
            units.append(item)
        return {"data": units}

    @app.post("/api/config/units", status_code=201)
    def create_unit(body: UnitBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        kode = body.kode.strip()
        scheme_kode = (body.scheme_kode or db.DEFAULT_SCHEME_KODE).strip()
        if not kode:
            fail(400, "invalid_kode")
        if conn.execute("SELECT 1 FROM unit WHERE kode = ?", (kode,)).fetchone():
            fail(409, "unit_exists")
        urutan = body.urutan or (
            conn.execute(
                "SELECT COALESCE(MAX(urutan), 0) + 1 FROM unit WHERE scheme_kode = ?", (scheme_kode,)
            ).fetchone()[0]
        )
        if conn.execute(
            "SELECT 1 FROM unit WHERE scheme_kode = ? AND urutan = ?", (scheme_kode, urutan)
        ).fetchone():
            fail(409, "urutan_exists")
        now = db.utcnow()
        conn.execute(
            """
            INSERT INTO unit (kode, scheme_kode, judul, urutan, aktif, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (kode, scheme_kode, normalize_space(body.judul), urutan, 1 if body.aktif else 0, now, now),
        )
        version = touch_config(
            conn,
            user["id"],
            "config_change",
            "unit",
            kode,
            new_value={"kode": kode, "scheme_kode": scheme_kode, "judul": body.judul, "urutan": urutan},
            scheme_kode=scheme_kode,
        )
        conn.execute("UPDATE unit SET version = ? WHERE kode = ?", (version, kode))
        conn.commit()
        row = conn.execute("SELECT * FROM unit WHERE kode = ?", (kode,)).fetchone()
        return {**dict(row), "indicators": [], "indicator_count": 0, "max_score": 0}

    @app.patch("/api/config/units/{kode}")
    def patch_unit(kode: str, body: UnitPatch, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM unit WHERE kode = ?", (kode,)).fetchone()
        if row is None:
            fail(404, "unit_not_found")
        scheme_kode = row["scheme_kode"]
        changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if "judul" in changes:
            changes["judul"] = normalize_space(changes["judul"])
        if "urutan" in changes:
            if conn.execute(
                "SELECT 1 FROM unit WHERE scheme_kode = ? AND urutan = ? AND kode != ?",
                (scheme_kode, changes["urutan"], kode),
            ).fetchone():
                fail(409, "urutan_exists")
        if "aktif" in changes:
            changes["aktif"] = 1 if changes["aktif"] else 0
        if not changes:
            return dict(row)
        bump = any(key in changes for key in ("urutan", "aktif"))
        fields = ", ".join(f"{key} = ?" for key in changes)
        conn.execute(
            f"UPDATE unit SET {fields}, updated_at = ? WHERE kode = ?",
            [*changes.values(), db.utcnow(), kode],
        )
        version = touch_config(
            conn, user["id"], "config_change", "unit", kode, dict(row), changes, bump=bump, scheme_kode=scheme_kode
        )
        if bump and version:
            conn.execute("UPDATE unit SET version = ? WHERE kode = ?", (version, kode))
        conn.commit()
        return dict(conn.execute("SELECT * FROM unit WHERE kode = ?", (kode,)).fetchone())

    @app.delete("/api/config/units/{kode}")
    def delete_unit(kode: str, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM unit WHERE kode = ?", (kode,)).fetchone()
        if row is None:
            fail(404, "unit_not_found")
        usage = conn.execute(
            "SELECT COUNT(*) FROM score s JOIN indicator i ON i.kode = s.indicator_kode WHERE i.unit_kode = ?",
            (kode,),
        ).fetchone()[0]
        if usage:
            fail(409, "unit_in_use", message="Unit sudah dipakai assessment")
        conn.execute("DELETE FROM unit WHERE kode = ?", (kode,))
        touch_config(
            conn, user["id"], "config_change", "unit", kode, old_value=dict(row), scheme_kode=row["scheme_kode"]
        )
        conn.commit()
        return {"ok": True}

    _register_indicator_and_sub_routes(app, auth_ctx)


def _register_indicator_and_sub_routes(app: FastAPI, auth_ctx: Any) -> None:
    @app.post("/api/config/units/{kode}/indicators", status_code=201)
    def create_indicator(kode: str, body: IndicatorBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        unit = conn.execute("SELECT * FROM unit WHERE kode = ?", (kode,)).fetchone()
        if unit is None:
            fail(404, "unit_not_found")
        ind_kode = (body.kode or indicator_next_code(conn)).strip()
        if conn.execute("SELECT 1 FROM indicator WHERE kode = ?", (ind_kode,)).fetchone():
            fail(409, "indicator_exists")
        urutan = body.urutan or (
            conn.execute(
                "SELECT COALESCE(MAX(urutan), 0) + 1 FROM indicator WHERE unit_kode = ?", (kode,)
            ).fetchone()[0]
        )
        if conn.execute("SELECT 1 FROM indicator WHERE unit_kode = ? AND urutan = ?", (kode, urutan)).fetchone():
            fail(409, "urutan_exists")
        now = db.utcnow()
        conn.execute(
            """
            INSERT INTO indicator
                (kode, unit_kode, teks, urutan, aktif, version, is_proposed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                ind_kode,
                kode,
                body.teks.strip(),
                urutan,
                1 if body.aktif else 0,
                1 if body.is_proposed else 0,
                now,
                now,
            ),
        )
        version = touch_config(
            conn,
            user["id"],
            "config_change",
            "indicator",
            ind_kode,
            new_value={"unit_kode": kode, "teks": body.teks, "urutan": urutan},
            scheme_kode=unit["scheme_kode"],
        )
        conn.execute("UPDATE indicator SET version = ? WHERE kode = ?", (version, ind_kode))
        conn.commit()
        return dict(conn.execute("SELECT * FROM indicator WHERE kode = ?", (ind_kode,)).fetchone())

    @app.patch("/api/config/indicators/{kode}")
    def patch_indicator(kode: str, body: IndicatorPatch, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM indicator WHERE kode = ?", (kode,)).fetchone()
        if row is None:
            fail(404, "indicator_not_found")
        unit = conn.execute("SELECT scheme_kode FROM unit WHERE kode = ?", (row["unit_kode"],)).fetchone()
        scheme_kode = unit["scheme_kode"] if unit else db.DEFAULT_SCHEME_KODE
        changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        if "teks" in changes:
            changes["teks"] = changes["teks"].strip()
        if "urutan" in changes:
            if conn.execute(
                "SELECT 1 FROM indicator WHERE unit_kode = ? AND urutan = ? AND kode != ?",
                (row["unit_kode"], changes["urutan"], kode),
            ).fetchone():
                fail(409, "urutan_exists")
        if "aktif" in changes:
            changes["aktif"] = 1 if changes["aktif"] else 0
        if not changes:
            return dict(row)
        bump = any(key in changes for key in ("urutan", "aktif"))
        fields = ", ".join(f"{key} = ?" for key in changes)
        conn.execute(
            f"UPDATE indicator SET {fields}, updated_at = ? WHERE kode = ?",
            [*changes.values(), db.utcnow(), kode],
        )
        version = touch_config(
            conn,
            user["id"],
            "config_change",
            "indicator",
            kode,
            dict(row),
            changes,
            bump=bump,
            scheme_kode=scheme_kode,
        )
        if bump and version:
            conn.execute("UPDATE indicator SET version = ? WHERE kode = ?", (version, kode))
        conn.commit()
        return dict(conn.execute("SELECT * FROM indicator WHERE kode = ?", (kode,)).fetchone())

    @app.delete("/api/config/indicators/{kode}")
    def delete_indicator(kode: str, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM indicator WHERE kode = ?", (kode,)).fetchone()
        if row is None:
            fail(404, "indicator_not_found")
        if conn.execute("SELECT COUNT(*) FROM score WHERE indicator_kode = ?", (kode,)).fetchone()[0]:
            fail(409, "indicator_in_use", message="Indikator sudah dipakai assessment")
        unit = conn.execute("SELECT scheme_kode FROM unit WHERE kode = ?", (row["unit_kode"],)).fetchone()
        conn.execute("DELETE FROM indicator WHERE kode = ?", (kode,))
        touch_config(
            conn,
            user["id"],
            "config_change",
            "indicator",
            kode,
            old_value=dict(row),
            scheme_kode=unit["scheme_kode"] if unit else db.DEFAULT_SCHEME_KODE,
        )
        conn.commit()
        return {"ok": True}

    def sub_payload(conn: sqlite3.Connection, row) -> dict[str, Any]:
        item = dict(row)
        item["unit_kodes"] = [
            r["unit_kode"]
            for r in conn.execute(
                "SELECT unit_kode FROM sub_competency_unit WHERE sub_competency_kode = ? ORDER BY unit_kode",
                (row["kode"],),
            )
        ]
        return item

    def validate_unit_codes(conn: sqlite3.Connection, codes: list[str]) -> list[str]:
        codes = list(dict.fromkeys(code.strip() for code in codes if code.strip()))
        if not codes:
            fail(400, "unit_kodes_required", message="Minimal satu unit penyusun")
        for code in codes:
            if conn.execute("SELECT 1 FROM unit WHERE kode = ? AND aktif = 1", (code,)).fetchone() is None:
                fail(400, "unit_not_found", unit_kode=code)
        return codes

    @app.get("/api/config/sub-competencies")
    def list_subs(scheme_kode: str = db.DEFAULT_SCHEME_KODE, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        rows = conn.execute(
            "SELECT * FROM sub_competency WHERE scheme_kode = ? ORDER BY urutan", (scheme_kode,)
        ).fetchall()
        return {"data": [sub_payload(conn, row) for row in rows]}

    @app.post("/api/config/sub-competencies", status_code=201)
    def create_sub(body: SubBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        kode = body.kode.strip()
        scheme_kode = (body.scheme_kode or db.DEFAULT_SCHEME_KODE).strip()
        if conn.execute("SELECT 1 FROM sub_competency WHERE kode = ?", (kode,)).fetchone():
            fail(409, "sub_exists")
        if conn.execute(
            "SELECT 1 FROM sub_competency WHERE scheme_kode = ? AND urutan = ?", (scheme_kode, body.urutan)
        ).fetchone():
            fail(409, "urutan_exists")
        codes = validate_unit_codes(conn, body.unit_kodes)
        now = db.utcnow()
        conn.execute(
            """
            INSERT INTO sub_competency (kode, scheme_kode, judul, urutan, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (kode, scheme_kode, normalize_space(body.judul), body.urutan, now, now),
        )
        for code in codes:
            conn.execute(
                "INSERT INTO sub_competency_unit (sub_competency_kode, unit_kode) VALUES (?, ?)", (kode, code)
            )
        version = touch_config(
            conn,
            user["id"],
            "config_change",
            "sub_competency",
            kode,
            new_value={"kode": kode, "scheme_kode": scheme_kode, "judul": body.judul, "unit_kodes": codes},
            scheme_kode=scheme_kode,
        )
        conn.execute("UPDATE sub_competency SET version = ? WHERE kode = ?", (version, kode))
        conn.commit()
        return sub_payload(conn, conn.execute("SELECT * FROM sub_competency WHERE kode = ?", (kode,)).fetchone())

    @app.patch("/api/config/sub-competencies/{kode}")
    def patch_sub(kode: str, body: SubPatch, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM sub_competency WHERE kode = ?", (kode,)).fetchone()
        if row is None:
            fail(404, "sub_not_found")
        scheme_kode = row["scheme_kode"]
        changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        codes = validate_unit_codes(conn, changes.pop("unit_kodes")) if "unit_kodes" in changes else None
        if "judul" in changes:
            changes["judul"] = normalize_space(changes["judul"])
        if "urutan" in changes:
            if conn.execute(
                "SELECT 1 FROM sub_competency WHERE scheme_kode = ? AND urutan = ? AND kode != ?",
                (scheme_kode, changes["urutan"], kode),
            ).fetchone():
                fail(409, "urutan_exists")
        bump = bool(codes) or "urutan" in changes
        old = sub_payload(conn, row)
        if changes:
            fields = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE sub_competency SET {fields}, updated_at = ? WHERE kode = ?",
                [*changes.values(), db.utcnow(), kode],
            )
        if codes is not None:
            conn.execute("DELETE FROM sub_competency_unit WHERE sub_competency_kode = ?", (kode,))
            for code in codes:
                conn.execute(
                    "INSERT INTO sub_competency_unit (sub_competency_kode, unit_kode) VALUES (?, ?)", (kode, code)
                )
        version = touch_config(
            conn,
            user["id"],
            "config_change",
            "sub_competency",
            kode,
            old,
            {**changes, **({"unit_kodes": codes} if codes is not None else {})},
            bump=bump,
            scheme_kode=scheme_kode,
        )
        if bump and version:
            conn.execute("UPDATE sub_competency SET version = ? WHERE kode = ?", (version, kode))
        conn.commit()
        return sub_payload(conn, conn.execute("SELECT * FROM sub_competency WHERE kode = ?", (kode,)).fetchone())

    @app.delete("/api/config/sub-competencies/{kode}")
    def delete_sub(kode: str, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM sub_competency WHERE kode = ?", (kode,)).fetchone()
        if row is None:
            fail(404, "sub_not_found")
        old = sub_payload(conn, row)
        conn.execute("DELETE FROM sub_competency WHERE kode = ?", (kode,))
        touch_config(
            conn, user["id"], "config_change", "sub_competency", kode, old_value=old, scheme_kode=row["scheme_kode"]
        )
        conn.commit()
        return {"ok": True}


def _register_sync_and_admin_routes(app: FastAPI, active_db_path: Path, db_dep: Any, auth_ctx: Any) -> None:
    @app.post("/api/sync/scores")
    def sync_scores(body: SyncScoresBody, request: Request, conn: sqlite3.Connection = Depends(db_dep)):
        expected_key = os.environ.get("SYNC_API_KEY", "")
        provided_key = request.headers.get("x-api-key", "")
        if expected_key and secrets.compare_digest(provided_key, expected_key):
            user_id = 1
        else:
            user = auth.require_user(conn, request)
            user_id = user["id"]
        synced = 0
        skipped = 0
        failed: list[dict[str, Any]] = []
        assessments: dict[int, Any] = {}
        for item in body.items:
            assessment = assessments.get(item.assessment_id)
            if assessment is None:
                assessment = conn.execute(
                    "SELECT * FROM assessment WHERE id = ?", (item.assessment_id,)
                ).fetchone()
                if assessment is None:
                    failed.append(
                        {
                            "assessment_id": item.assessment_id,
                            "indicator_kode": item.indicator_kode,
                            "error": "assessment_not_found",
                        }
                    )
                    continue
                assessments[item.assessment_id] = assessment
            status = apply_score_item(conn, assessment, item, user_id, body.client_ts)
            if status == "synced":
                synced += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed.append(
                    {"assessment_id": item.assessment_id, "indicator_kode": item.indicator_kode, "error": status}
                )
        db.set_config(conn, "last_scores_sync", db.utcnow())
        conn.commit()
        return {"synced": synced, "skipped": skipped, "failed": failed}

    @app.get("/api/sync/status")
    def sync_status(ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        pending_scores = conn.execute("SELECT COUNT(*) FROM score WHERE synced = 0").fetchone()[0]
        pending_sheets = conn.execute(
            "SELECT COUNT(*) FROM sync_outbox WHERE payload_type = 'sheets' AND status IN ('pending','processing')"
        ).fetchone()[0]
        failed = conn.execute(
            """
            SELECT idempotency_key, payload_type, retry_count, last_error, created_at
            FROM sync_outbox WHERE status = 'failed' ORDER BY id DESC LIMIT 20
            """
        ).fetchall()
        config = db.all_config(conn)
        return {
            "pending_scores": pending_scores,
            "pending_sheets": pending_sheets,
            "last_scores_sync": config.get("last_scores_sync"),
            "last_sheets_sync": config.get("last_sheets_sync"),
            "failed_items": [dict(row) for row in failed],
            "sheets": sheets.status(conn=conn),
            "backup_dir_configured": bool(os.environ.get("BACKUP_DIR")),
        }

    @app.post("/api/sync/sheets/config")
    def save_sheets_config(body: SheetsConfigBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        sheet_id = sheets.extract_spreadsheet_id(body.spreadsheet_url_or_id)
        if not sheet_id:
            fail(400, "invalid_spreadsheet_id", message="URL atau ID Google Spreadsheet tidak valid.")
        raw_json = (body.service_account_json or "").strip()
        if raw_json:
            try:
                parsed = json.loads(raw_json)
            except Exception:
                fail(400, "invalid_service_account_json", message="File atau teks JSON Service Account tidak valid.")
            if (
                not isinstance(parsed, dict)
                or parsed.get("type") != "service_account"
                or not parsed.get("client_email")
                or not parsed.get("private_key")
            ):
                fail(
                    400,
                    "invalid_service_account_json",
                    message="JSON harus berupa kunci Service Account Google (memiliki client_email dan private_key).",
                )
            db.set_config(conn, "google_service_account_json", json.dumps(parsed))
        db.set_config(conn, "google_sheets_id", sheet_id)
        db.audit(
            conn,
            user["id"],
            "sheets_config_update",
            "config",
            "google_sheets",
            new_value={"spreadsheet_id": sheet_id, "updated_credentials": bool(raw_json)},
        )
        conn.commit()
        return sheets.status(conn=conn)

    @app.delete("/api/sync/sheets/config")
    def clear_sheets_config(ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        db.set_config(conn, "google_sheets_id", "")
        db.set_config(conn, "google_service_account_json", "")
        db.audit(conn, user["id"], "sheets_config_clear", "config", "google_sheets")
        conn.commit()
        return sheets.status(conn=conn)

    @app.post("/api/sync/sheets/test")
    def test_sheets_connection(ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        result = sheets.test_connection(conn=conn)
        if not result.get("ok"):
            fail(400, "sheets_test_failed", message=result.get("message"))
        return result

    @app.post("/api/sync/sheets")
    def sync_sheets(body: SheetsBody, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        if body.exam_id is not None and body.school_id is not None:
            if conn.execute(
                "SELECT 1 FROM exam_school WHERE exam_id=? AND school_id=?",
                (body.exam_id, body.school_id),
            ).fetchone() is None:
                fail(400, "school_not_associated")
        info = sheets.sync_schools(body.school_id, body.exam_id, active_db_path)
        status = info.get("status", "error")
        db.record_outbox(
            conn,
            "sheets",
            f"sheets:{body.exam_id or 'legacy'}:{body.school_id or 'all'}:{db.utcnow()}",
            info,
            status="done" if status in {"ok", "disabled"} else "failed",
            error=info.get("message"),
        )
        if status == "ok":
            db.set_config(conn, "last_sheets_sync", db.utcnow())
        db.audit(
            conn,
            user["id"],
            "sheets_sync",
            "school",
            body.exam_id or body.school_id or "all",
            new_value={"status": status, "rows": info.get("rows_upserted", 0), "exam_id": body.exam_id},
        )
        conn.commit()
        if status == "error":
            fail(502, "sheets_sync_failed", message=info.get("message"))
        return info

    @app.post("/api/admin/backup")
    def admin_backup(ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        try:
            info = backup.create_backup(active_db_path)
        except Exception as exc:
            fail(500, "backup_failed", message=str(exc)[:200])
        db.audit(conn, user["id"], "backup", "system", info["filename"], new_value=info)
        conn.commit()
        return info

    @app.get("/api/admin/backups")
    def admin_backups(ctx: tuple = Depends(auth_ctx)):
        return {"backups": backup.list_backups()}

    @app.get("/api/audit")
    def get_audit(
        entity_type: str | None = None,
        entity_id: str | None = None,
        action: str | None = None,
        limit: int = 200,
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        clauses: list[str] = []
        values: list[Any] = []
        if entity_type:
            clauses.append("entity_type = ?")
            values.append(entity_type)
        if entity_id:
            clauses.append("entity_id = ?")
            values.append(entity_id)
        if action:
            clauses.append("action = ?")
            values.append(action)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(limit, 1000))
        rows = conn.execute(
            f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?", (*values, limit)
        ).fetchall()
        return {"data": [dict(row) for row in rows], "meta": {"total": len(rows)}}

    @app.get("/api/health")
    def health():
        with db.open_db(active_db_path) as conn:
            conn.execute("SELECT 1")
            units = conn.execute(
                "SELECT COUNT(*) FROM unit WHERE scheme_kode = ?", (db.DEFAULT_SCHEME_KODE,)
            ).fetchone()[0]
            indicators = conn.execute(
                """
                SELECT COUNT(*) FROM indicator i
                JOIN unit u ON u.kode = i.unit_kode
                WHERE u.scheme_kode = ?
                """,
                (db.DEFAULT_SCHEME_KODE,),
            ).fetchone()[0]
            schemes_count = conn.execute("SELECT COUNT(*) FROM scheme").fetchone()[0]
        return {
            "status": "ok",
            "db": "ok",
            "time": db.utcnow(),
            "units": units,
            "indicators": indicators,
            "schemes": schemes_count,
        }

    @app.get("/healthz")
    def healthz():
        return health()

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        return "User-agent: *\nDisallow: /\n"


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------
def create_app(db_path: str | os.PathLike[str] | None = None) -> FastAPI:
    active_db_path = db.init_db(db_path)
    app = FastAPI(
        title="AeroAssess — Multi-Scheme Assessor & Competency Portal",
        version="2.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.db_path = active_db_path
    app.state.rate_limiter = auth.LoginRateLimiter()

    def db_dep() -> Iterator[sqlite3.Connection]:
        conn = db.connect(active_db_path)
        try:
            yield conn
        finally:
            conn.close()

    def auth_ctx(request: Request, conn: sqlite3.Connection = Depends(db_dep)) -> tuple[sqlite3.Connection, dict[str, Any]]:
        return conn, auth.require_user(conn, request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(exc.detail, status_code=exc.status_code)
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(part) for part in err.get("loc", [])), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse({"error": "validation_error", "details": details}, status_code=400)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        if request.method in MUTATION_METHODS and request.url.path.startswith("/api/"):
            api_key_sync = request.url.path == "/api/sync/scores" and bool(request.headers.get("x-api-key"))
            if not api_key_sync and request.headers.get("x-requested-with", "").lower() != "fetch":
                return JSONResponse({"error": "csrf_required"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if auth.cookie_secure() or os.environ.get("HSTS", "").lower() in {"1", "true", "yes"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    _register_auth_routes(app, db_dep, auth_ctx)
    _register_scheme_and_recap_routes(app, auth_ctx)
    _register_school_routes(app, auth_ctx)
    exams.register_routes(app, auth_ctx)
    _register_assessment_routes(app, auth_ctx)
    _register_config_routes(app, auth_ctx)
    _register_sync_and_admin_routes(app, active_db_path, db_dep, auth_ctx)

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
