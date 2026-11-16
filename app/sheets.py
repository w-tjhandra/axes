"""Sinkron satu arah ke Google Sheets. Disabled-safe bila env tidak lengkap."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from . import db, rules
except ImportError:  # pragma: no cover
    import db  # type: ignore[no-redef]
    import rules  # type: ignore[no-redef]

INVALID_TAB_CHARS = re.compile(r"[\[\]:*?/\\]")
SYSTEM_TAB_NAMES = {"", "history", "ringkasan", "config", "sheet1"}
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def extract_spreadsheet_id(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    match = SPREADSHEET_URL_RE.search(text)
    if match:
        return match.group(1)
    return text


def _load_service_account_info(raw_json: str, env_path: str) -> tuple[dict[str, Any] | None, str | None]:
    if raw_json:
        try:
            info = json.loads(raw_json)
            if isinstance(info, dict) and info.get("client_email") and info.get("private_key"):
                return info, None
            return None, "Format JSON service account tidak valid (client_email / private_key kosong)"
        except Exception:
            return None, "JSON service account tidak dapat dibaca"
    if env_path:
        path = Path(env_path).expanduser()
        if not path.exists():
            return None, "File service account tidak ditemukan"
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(info, dict) and info.get("client_email") and info.get("private_key"):
                return info, None
            return None, "Format file JSON service account tidak valid"
        except Exception:
            return None, "File JSON service account tidak dapat dibaca"
    return None, None


def resolve_settings(
    db_path: str | os.PathLike[str] | None = None,
    conn=None,
) -> dict[str, Any]:
    own_conn = conn is None
    if own_conn:
        conn = db.connect(db_path)
    try:
        config = db.all_config(conn)
    finally:
        if own_conn:
            conn.close()

    ui_sheet_id = extract_spreadsheet_id(config.get("google_sheets_id"))
    ui_json = (config.get("google_service_account_json") or "").strip()
    env_sheet_id = extract_spreadsheet_id(os.environ.get("GOOGLE_SHEETS_ID", ""))
    env_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    sheet_id = ui_sheet_id or env_sheet_id
    source = "ui" if (ui_sheet_id or ui_json) else ("env" if (env_sheet_id or env_path) else "none")
    info, err = _load_service_account_info(ui_json, env_path if not ui_json else "")
    return {
        "spreadsheet_id": sheet_id,
        "service_account_info": info,
        "service_account_email": info.get("client_email") if info else None,
        "has_credentials": info is not None,
        "credentials_error": err,
        "source": source,
    }


def status(db_path: str | os.PathLike[str] | None = None, conn=None) -> dict[str, Any]:
    cfg = resolve_settings(db_path=db_path, conn=conn)
    sheet_id = cfg["spreadsheet_id"]
    if cfg["credentials_error"]:
        return {
            "status": "disabled",
            "enabled": False,
            "reason": cfg["credentials_error"],
            "spreadsheet_configured": bool(sheet_id),
            "spreadsheet_id": sheet_id,
            "service_account_email": cfg["service_account_email"],
            "has_credentials": False,
            "source": cfg["source"],
        }
    if not cfg["has_credentials"] or not sheet_id:
        return {
            "status": "disabled",
            "enabled": False,
            "reason": "Spreadsheet ID atau JSON Service Account belum diatur",
            "spreadsheet_configured": bool(sheet_id),
            "spreadsheet_id": sheet_id,
            "service_account_email": cfg["service_account_email"],
            "has_credentials": cfg["has_credentials"],
            "source": cfg["source"],
        }
    return {
        "status": "enabled",
        "enabled": True,
        "reason": None,
        "spreadsheet_configured": True,
        "spreadsheet_id": sheet_id,
        "service_account_email": cfg["service_account_email"],
        "has_credentials": True,
        "source": cfg["source"],
    }


def sanitize_tab_name(name: str, fallback: str = "Sekolah") -> str:
    cleaned = INVALID_TAB_CHARS.sub("_", (name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_")
    if cleaned.lower() in SYSTEM_TAB_NAMES:
        cleaned = f"{fallback}_{cleaned}".strip("_")
    if not cleaned:
        cleaned = fallback
    return cleaned[:100]


def _latest_assessment(conn, participant_id: int):
    return conn.execute(
        "SELECT * FROM assessment WHERE participant_id = ? ORDER BY id DESC LIMIT 1",
        (participant_id,),
    ).fetchone()


def _result_for(conn, assessment_row, config: dict[str, Any]) -> dict[str, Any] | None:
    if assessment_row is None:
        return None
    snapshot = json.loads(assessment_row["instrument_json"])
    if assessment_row["status"] == "locked" and assessment_row["result_json"]:
        return json.loads(assessment_row["result_json"])
    scores = {
        row["indicator_kode"]: row["value"]
        for row in conn.execute(
            "SELECT indicator_kode, value FROM score WHERE assessment_id = ?",
            (assessment_row["id"],),
        )
    }
    participant = conn.execute(
        "SELECT nama, nomor FROM participant WHERE id = ?",
        (assessment_row["participant_id"],),
    ).fetchone()
    label = rules.participant_label(participant["nama"], participant["nomor"])
    return rules.compute_result(
        snapshot.get("units", []),
        snapshot.get("sub_competencies", []),
        scores,
        label,
        config,
    )


def _headers(snapshot: dict[str, Any]) -> list[str]:
    unit_codes = [u["kode"] for u in snapshot.get("units", [])]
    return [
        "Nomor",
        "Nama",
        "Kelas",
        "Status",
        *unit_codes,
        "Unit Lulus",
        "Unit Tidak Lulus",
        "Sub Kompetensi",
        "Predikat",
        "Pernyataan",
        "Locked At",
    ]


def _rows_for_school(conn, school_id: int, config: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    participants = conn.execute(
        "SELECT * FROM participant WHERE school_id = ? ORDER BY nomor", (school_id,)
    ).fetchall()
    snapshot = db.get_snapshot(conn)
    headers = _headers(snapshot)
    rows: list[list[Any]] = []
    for participant in participants:
        assessment = _latest_assessment(conn, participant["id"])
        result = _result_for(conn, assessment, config)
        unit_values: list[Any] = []
        if result:
            percent_by_code = {u["kode"]: u["percent"] for u in result.get("unit_results", [])}
            unit_values = [
                percent_by_code.get(code, "") for code in [u["kode"] for u in snapshot.get("units", [])]
            ]
        sub_text = ""
        if result and result.get("selected_sub"):
            sub_text = result["selected_sub"]["judul"]
        elif result:
            sub_text = "; ".join(s["judul"] for s in result.get("sub_fulfilled", []))
        rows.append(
            [
                participant["nomor"],
                participant["nama"],
                participant["kelas"] or "",
                assessment["status"] if assessment else "belum_mulai",
                *unit_values,
                ", ".join(result.get("unit_passed", [])) if result else "",
                ", ".join(result.get("unit_failed", [])) if result else "",
                sub_text,
                (result or {}).get("predicate") or "",
                (result or {}).get("statement") or "",
                (assessment["locked_at"] if assessment else "") or "",
            ]
        )
    return headers, rows


def _rows_for_exam_school(
    conn, exam_id: int, school_id: int, config: dict[str, Any]
) -> tuple[list[str], list[list[Any]]]:
    exam = conn.execute("SELECT * FROM exam WHERE id=?", (exam_id,)).fetchone()
    school = conn.execute("SELECT * FROM school WHERE id=?", (school_id,)).fetchone()
    if exam is None or school is None:
        raise ValueError("Ujian atau sekolah tidak ditemukan")
    scheme_kode = school["scheme_kode"]
    snapshot = db.get_snapshot(conn, scheme_kode)
    unit_codes = [unit["kode"] for unit in snapshot.get("units", [])]
    headers = [
        "Idempotency Key",
        "Exam ID",
        "Judul Ujian",
        "Tahun",
        "Sekolah",
        "Nomor",
        "Nama",
        "Kelas",
        "Kelompok",
        "Skema",
        "Status Pendaftaran",
        "Status Asesmen",
        *unit_codes,
        "Unit Lulus",
        "Unit Tidak Lulus",
        "Sub Kompetensi",
        "Predikat",
        "Outcome",
        "Locked At",
    ]
    enrollments = conn.execute(
        """SELECT ee.*, a.id AS assessment_id, a.participant_id AS assessment_participant_id,
                  a.status AS assessment_status, a.instrument_json, a.result_json, a.locked_at
           FROM exam_enrollment ee
           LEFT JOIN assessment a ON a.exam_enrollment_id=ee.id
           WHERE ee.exam_id=? AND ee.school_id=? ORDER BY ee.snapshot_number, ee.id""",
        (exam_id, school_id),
    ).fetchall()
    rows: list[list[Any]] = []
    for enrollment in enrollments:
        assessment = None
        result = None
        if enrollment["assessment_id"] is not None:
            assessment = {
                "id": enrollment["assessment_id"],
                "participant_id": enrollment["assessment_participant_id"],
                "status": enrollment["assessment_status"],
                "instrument_json": enrollment["instrument_json"],
                "result_json": enrollment["result_json"],
                "locked_at": enrollment["locked_at"],
            }
            result = _result_for(conn, assessment, config)
        percent_by_code = {
            unit["kode"]: unit.get("percent", "")
            for unit in (result or {}).get("unit_results", [])
        }
        selected_sub = (result or {}).get("selected_sub")
        sub_text = (
            selected_sub["judul"]
            if selected_sub
            else "; ".join(sub["judul"] for sub in (result or {}).get("sub_fulfilled", []))
        )
        rows.append(
            [
                f"{exam_id}:{enrollment['id']}",
                exam_id,
                exam["title"],
                exam["year"],
                enrollment["snapshot_school_name"],
                enrollment["snapshot_number"],
                enrollment["snapshot_name"],
                enrollment["snapshot_class"],
                enrollment["group_label"],
                enrollment["scheme_kode"],
                enrollment["status"],
                (assessment or {}).get("status", "belum_mulai"),
                *[percent_by_code.get(code, "") for code in unit_codes],
                ", ".join((result or {}).get("unit_passed", [])),
                ", ".join((result or {}).get("unit_failed", [])),
                sub_text,
                (result or {}).get("predicate") or "",
                (result or {}).get("outcome") or "",
                enrollment["locked_at"] or "",
            ]
        )
    return headers, rows


def _build_service(service_account_info: dict[str, Any]):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def test_connection(db_path: str | os.PathLike[str] | None = None, conn=None) -> dict[str, Any]:
    cfg = resolve_settings(db_path=db_path, conn=conn)
    if cfg["credentials_error"]:
        return {"ok": False, "message": cfg["credentials_error"]}
    if not cfg["has_credentials"] or not cfg["spreadsheet_id"]:
        return {"ok": False, "message": "Spreadsheet ID atau JSON Service Account belum lengkap."}
    try:
        service = _build_service(cfg["service_account_info"])
        meta = (
            service.spreadsheets()
            .get(
                spreadsheetId=cfg["spreadsheet_id"],
                fields="properties.title,sheets.properties.title",
            )
            .execute()
        )
        tabs = [item["properties"]["title"] for item in meta.get("sheets", [])]
        return {
            "ok": True,
            "title": meta.get("properties", {}).get("title", "Spreadsheet"),
            "tabs": tabs,
            "spreadsheet_id": cfg["spreadsheet_id"],
        }
    except Exception as exc:
        msg = str(exc)
        if "403" in msg or "permission" in msg.lower():
            email = cfg["service_account_email"] or "service account"
            return {
                "ok": False,
                "message": f"Akses ditolak (403). Pastikan Spreadsheet sudah di-Share ke {email} sebagai Editor.",
            }
        if "404" in msg or "not found" in msg.lower():
            return {"ok": False, "message": "Spreadsheet tidak ditemukan (404). Periksa kembali URL atau ID Spreadsheet."}
        return {"ok": False, "message": f"Gagal terhubung ke Google Sheets: {msg}"}


def _ensure_tab(service, spreadsheet_id: str, tab: str, known_tabs: dict[str, int]) -> None:
    if tab in known_tabs:
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
    ).execute()
    known_tabs[tab] = -1


def sync_schools(
    school_id: int | None = None,
    exam_id: int | None = None,
    db_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Push hasil sekolah ke Sheets. Tidak pernah melempar error ke caller."""
    conn = db.connect(db_path)
    try:
        cfg = resolve_settings(conn=conn)
        state = status(conn=conn)
        if not state["enabled"]:
            return {
                "status": "disabled",
                "synced_schools": 0,
                "rows_upserted": 0,
                "message": state["reason"],
            }

        config = db.all_config(conn)
        if exam_id is not None:
            exam = conn.execute("SELECT * FROM exam WHERE id=?", (exam_id,)).fetchone()
            if exam is None:
                return {"status": "error", "synced_schools": 0, "rows_upserted": 0, "message": "Ujian tidak ditemukan"}
            if school_id is not None:
                schools = conn.execute(
                    """SELECT s.* FROM school s JOIN exam_school es ON es.school_id=s.id
                       WHERE es.exam_id=? AND s.id=?""",
                    (exam_id, school_id),
                ).fetchall()
                if not schools:
                    return {"status": "error", "synced_schools": 0, "rows_upserted": 0, "message": "Sekolah tidak terdaftar pada ujian"}
            else:
                schools = conn.execute(
                    """SELECT s.* FROM school s JOIN exam_school es ON es.school_id=s.id
                       WHERE es.exam_id=? ORDER BY s.nama""",
                    (exam_id,),
                ).fetchall()
        elif school_id is not None:
            schools = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchall()
        else:
            schools = conn.execute("SELECT * FROM school ORDER BY nama").fetchall()
        if not schools:
            return {"status": "ok", "synced_schools": 0, "rows_upserted": 0, "message": "Tidak ada sekolah"}

        service = _build_service(cfg["service_account_info"])
        spreadsheet_id = cfg["spreadsheet_id"]
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
            .execute()
        )
        known_tabs = {
            item["properties"]["title"]: item["properties"].get("sheetId", -1)
            for item in meta.get("sheets", [])
        }

        used_tabs: set[str] = set(known_tabs)
        synced_schools = 0
        rows_upserted = 0
        for school in schools:
            tab_name = f"{exam['year']}_{exam['title']}_{school['nama']}" if exam_id is not None else school["nama"]
            tab = sanitize_tab_name(tab_name, "Ujian" if exam_id is not None else "Sekolah")
            if tab in used_tabs:
                tab = f"{tab[:85]}_{exam_id or 'legacy'}_{school['id']}"
                while tab in used_tabs:
                    tab = f"{tab[:80]}_{exam_id or 'legacy'}_{school['id']}_x"
            used_tabs.add(tab)
            _ensure_tab(service, spreadsheet_id, tab, known_tabs)

            if exam_id is not None:
                headers, rows = _rows_for_exam_school(conn, exam_id, school["id"], config)
            else:
                headers, rows = _rows_for_school(conn, school["id"], config)
            existing_values = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=f"'{tab}'!A2:A")
                .execute()
                .get("values", [])
            )
            existing_rows = {
                str(row[0]).strip(): index + 2
                for index, row in enumerate(existing_values)
                if row and str(row[0]).strip()
            }

            data: list[dict[str, Any]] = [
                {"range": f"'{tab}'!A1", "values": [headers]},
            ]
            last_col = _column_letter(len(headers))
            next_row = max(existing_rows.values(), default=1) + 1
            for row in rows:
                nomor = str(row[0]).strip()
                row_index = existing_rows.get(nomor)
                if row_index:
                    data.append({"range": f"'{tab}'!A{row_index}:{last_col}{row_index}", "values": [row]})
                else:
                    data.append({"range": f"'{tab}'!A{next_row}:{last_col}{next_row}", "values": [row]})
                    existing_rows[nomor] = next_row
                    next_row += 1
                rows_upserted += 1
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ).execute()
            synced_schools += 1
        return {
            "status": "ok",
            "synced_schools": synced_schools,
            "rows_upserted": rows_upserted,
            "exam_id": exam_id,
            "message": None,
        }
    except Exception as exc:  # jangan crash: kembalikan status error yang aman
        return {
            "status": "error",
            "synced_schools": 0,
            "rows_upserted": 0,
            "message": f"Sinkron Sheets gagal: {type(exc).__name__}",
        }
    finally:
        conn.close()


def _column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
