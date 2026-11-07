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


def status() -> dict[str, Any]:
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "").strip()
    if not path or not sheet_id:
        return {
            "status": "disabled",
            "enabled": False,
            "reason": "GOOGLE_SERVICE_ACCOUNT_JSON atau GOOGLE_SHEETS_ID belum diset",
            "spreadsheet_configured": bool(sheet_id),
        }
    if not Path(path).expanduser().exists():
        return {
            "status": "disabled",
            "enabled": False,
            "reason": "File service account tidak ditemukan",
            "spreadsheet_configured": True,
        }
    return {"status": "enabled", "enabled": True, "reason": None, "spreadsheet_configured": True}


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


def _build_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], scopes=SCOPES
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _ensure_tab(service, spreadsheet_id: str, tab: str, known_tabs: dict[str, int]) -> None:
    if tab in known_tabs:
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
    ).execute()
    known_tabs[tab] = -1


def sync_schools(school_id: int | None = None) -> dict[str, Any]:
    """Push hasil sekolah ke Sheets. Tidak pernah melempar error ke caller."""
    state = status()
    if not state["enabled"]:
        return {
            "status": "disabled",
            "synced_schools": 0,
            "rows_upserted": 0,
            "message": state["reason"],
        }

    conn = db.connect()
    try:
        config = db.all_config(conn)
        if school_id is not None:
            schools = conn.execute("SELECT * FROM school WHERE id = ?", (school_id,)).fetchall()
        else:
            schools = conn.execute("SELECT * FROM school ORDER BY nama").fetchall()
        if not schools:
            return {"status": "ok", "synced_schools": 0, "rows_upserted": 0, "message": "Tidak ada sekolah"}

        service = _build_service()
        spreadsheet_id = os.environ["GOOGLE_SHEETS_ID"]
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
            tab = sanitize_tab_name(school["nama"], "Sekolah")
            if tab in used_tabs:
                tab = f"{tab[:94]}_{school['id']}"
                while tab in used_tabs:
                    tab = f"{tab[:90]}_{school['id']}_x"
            used_tabs.add(tab)
            _ensure_tab(service, spreadsheet_id, tab, known_tabs)

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
