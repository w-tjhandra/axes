"""Mesin rekapitulasi otomatis lintas skema dan generator ekspor CSV/XLSX yang aman.

Penjelasan Teknis (1-2 kalimat): Modul ini memisahkan beban agregasi analitik dan pembuatan
file spreadsheet dari `main.py` (konsep *separation of concerns*), serta menyaring karakter awal
`=`, `+`, `-`, `@` pada teks untuk mencegah serangan *CSV/Excel Formula Injection* (CWE-1236).
"""

from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from fastapi.responses import Response

try:
    from . import db
except ImportError:  # pragma: no cover
    import db  # type: ignore[no-redef]

FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value: Any) -> Any:
    """Bersihkan karakter kontrol dan cegah CSV/Spreadsheet Formula Injection (CWE-1236)."""
    if not isinstance(value, str):
        return value
    cleaned = "".join(ch for ch in value if ch in "\n\r\t" or ord(ch) >= 32)
    if cleaned.startswith(FORMULA_TRIGGERS):
        return f"'{cleaned}"
    return cleaned


def column_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _extract_row_values(row: dict[str, Any], units: list[dict[str, Any]], include_school: bool = False) -> list[Any]:
    p = row["participant"]
    result = row["result"] or {}
    unit_map = {u["kode"]: u for u in result.get("unit_results", [])}
    sub_label = (
        (result.get("selected_sub") or {}).get("judul", "")
        if result.get("selected_sub")
        else "; ".join(s["judul"] for s in result.get("sub_fulfilled", []))
    )
    prefix = [row.get("school_nama", ""), row.get("scheme_kode", "")] if include_school else []
    base = [
        *prefix,
        p["nomor"],
        p["nama"],
        p["kelas"] or "",
        row["status"],
        len(result.get("unit_passed", [])),
        ", ".join(result.get("unit_passed", [])),
        ", ".join(result.get("unit_failed", [])),
        result.get("predicate") or "",
        result.get("outcome_label") or "",
        sub_label,
        result.get("statement") or "",
        row["locked_at"] or "",
    ]
    for unit in units:
        summary = unit_map.get(unit["kode"], {})
        status_txt = ""
        if summary:
            status_txt = "Lulus" if summary.get("passed") else "Belum"
        base.extend([summary.get("percent", ""), status_txt])
    return [sanitize_cell(v) for v in base]


def build_export_csv(
    rows: list[dict[str, Any]],
    units: list[dict[str, Any]],
    safe_kode: str,
    stamp: str,
    include_school: bool = False,
) -> Response:
    """Bangun respons CSV UTF-8-BOM untuk satu sekolah atau satu skema penuh."""
    prefix = ["sekolah", "skema"] if include_school else []
    headers = [
        *prefix,
        "nomor",
        "nama",
        "kelas",
        "status",
        "jumlah_unit_lulus",
        "unit_lulus",
        "unit_tidak_lulus",
        "predikat",
        "hasil",
        "sub_kompetensi",
        "pernyataan",
        "locked_at",
    ]
    for unit in units:
        headers.extend([f"{unit['kode']}_persen", f"{unit['kode']}_status"])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(_extract_row_values(row, units, include_school))
    content = "\ufeff" + output.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="hasil_{safe_kode}_{stamp}.csv"'},
    )


def _populate_unit_and_sub_sheets(wb: Any, rows: list[dict[str, Any]]) -> None:
    ws2 = wb.create_sheet("Detail Unit")
    ws2.append(
        [
            "Nomor",
            "Nama",
            "Kelas",
            "Unit Kode",
            "Unit Judul",
            "Skor",
            "Maks",
            "Persen",
            "Status",
            "Indikator Terisi",
            "Indikator Kosong",
        ]
    )
    for row in rows:
        p = row["participant"]
        result = row["result"] or {}
        for unit in result.get("unit_results", []):
            ws2.append(
                [
                    sanitize_cell(p["nomor"]),
                    sanitize_cell(p["nama"]),
                    sanitize_cell(p["kelas"] or ""),
                    unit["kode"],
                    sanitize_cell(unit["judul"]),
                    unit["total_score"],
                    unit["max_score"],
                    unit["percent"],
                    "Lulus" if unit["passed"] else "Belum",
                    unit["filled"],
                    unit["empty_count"],
                ]
            )

    ws3 = wb.create_sheet("Sub Kompetensi")
    ws3.append(
        [
            "Nomor",
            "Nama",
            "Kelas",
            "Sub Kode",
            "Sub Kompetensi",
            "Terpenuhi",
            "Rata-rata Persen",
            "Terpilih",
        ]
    )
    for row in rows:
        p = row["participant"]
        result = row["result"] or {}
        selected = (result.get("selected_sub") or {}).get("kode")
        for sub in result.get("sub_competencies", []):
            ws3.append(
                [
                    sanitize_cell(p["nomor"]),
                    sanitize_cell(p["nama"]),
                    sanitize_cell(p["kelas"] or ""),
                    sub["kode"],
                    sanitize_cell(sub["judul"]),
                    "Ya" if sub["fulfilled"] else "Tidak",
                    sub["average_percent"],
                    "Ya" if sub["kode"] == selected else "",
                ]
            )


def build_export_xlsx(
    rows: list[dict[str, Any]],
    units: list[dict[str, Any]],
    safe_kode: str,
    stamp: str,
    include_school: bool = False,
) -> Response:
    """Bangun file XLSX 3-sheet (Ringkasan, Detail Unit, Sub Kompetensi)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Ringkasan"
    prefix = ["Sekolah", "Skema"] if include_school else []
    headers = [
        *prefix,
        "Nomor",
        "Nama",
        "Kelas",
        "Status",
        "Jumlah Unit Lulus",
        "Unit Lulus",
        "Unit Tidak Lulus",
        "Predikat",
        "Hasil",
        "Sub Kompetensi",
        "Pernyataan",
        "Locked At",
    ]
    for unit in units:
        headers.extend([f"{unit['kode']} (%)", f"{unit['kode']} Status"])
    ws.append(headers)
    for row in rows:
        ws.append(_extract_row_values(row, units, include_school))

    _populate_unit_and_sub_sheets(wb, rows)

    header_font = Font(bold=True)
    fill = PatternFill("solid", fgColor="EEF2FF")
    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = header_font
            cell.fill = fill
        sheet.freeze_panes = "A2"
        for column_cells in sheet.columns:
            max_len = max((len(str(c.value)) if c.value is not None else 0) for c in column_cells)
            sheet.column_dimensions[column_letter(column_cells[0].column)].width = min(
                48, max(10, max_len + 2)
            )

    buffer = io.BytesIO()
    wb.save(buffer)
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="hasil_{safe_kode}_{stamp}.xlsx"'},
    )


def compute_recap_summary(
    conn: sqlite3.Connection,
    compute_fn: Any,
    scheme_kode: str | None = None,
    school_id: int | None = None,
) -> dict[str, Any]:
    """Hitung rekapitulasi otomatis lintas sekolah dan skema (pengganti rekap manual Google Sheet)."""
    clauses: list[str] = []
    params: list[Any] = []
    if scheme_kode and scheme_kode != "all":
        clauses.append("s.scheme_kode = ?")
        params.append(scheme_kode)
    if school_id is not None:
        clauses.append("s.id = ?")
        params.append(school_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    schools = conn.execute(
        f"""
        SELECT s.*, sc.nama AS scheme_nama
        FROM school s
        LEFT JOIN scheme sc ON sc.kode = s.scheme_kode
        {where}
        ORDER BY s.nama
        """,
        params,
    ).fetchall()

    outcomes = {
        "kompeten_penuh": 0,
        "kompeten_sub": 0,
        "kompeten_unit": 0,
        "belum_kompeten": 0,
    }
    predicates = {
        "Sangat Mahir": 0,
        "Mahir": 0,
        "Cakap": 0,
        "Tidak Memenuhi": 0,
    }
    status_counts = {"participants": 0, "locked": 0, "in_progress": 0, "not_started": 0}
    unit_stats: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    for school in schools:
        participants = conn.execute(
            "SELECT * FROM participant WHERE school_id = ? ORDER BY nomor", (school["id"],)
        ).fetchall()
        for p in participants:
            status_counts["participants"] += 1
            assessment = conn.execute(
                "SELECT * FROM assessment WHERE participant_id = ? ORDER BY id DESC LIMIT 1",
                (p["id"],),
            ).fetchone()
            state = assessment["status"] if assessment else "not_started"
            if state == "locked":
                status_counts["locked"] += 1
            elif state == "in_progress":
                status_counts["in_progress"] += 1
            else:
                status_counts["not_started"] += 1

            result = compute_fn(conn, assessment) if assessment else None
            if result:
                out_key = result.get("outcome", "belum_kompeten")
                if out_key in outcomes:
                    outcomes[out_key] += 1
                pred_key = result.get("predicate") or "Tidak Memenuhi"
                predicates[pred_key] = predicates.get(pred_key, 0) + 1
                for ures in result.get("unit_results", []):
                    ukode = ures["kode"]
                    entry = unit_stats.setdefault(
                        ukode,
                        {
                            "kode": ukode,
                            "judul": ures["judul"],
                            "scheme_kode": school["scheme_kode"],
                            "assessed_count": 0,
                            "passed_count": 0,
                            "sum_percent": 0.0,
                        },
                    )
                    entry["assessed_count"] += 1
                    if ures.get("passed"):
                        entry["passed_count"] += 1
                    entry["sum_percent"] += float(ures.get("percent", 0.0))

            rows.append(
                {
                    "school_id": school["id"],
                    "school_nama": school["nama"],
                    "school_kode": school["kode"],
                    "scheme_kode": school["scheme_kode"],
                    "scheme_nama": school["scheme_nama"] or school["scheme_kode"],
                    "nomor": p["nomor"],
                    "nama": p["nama"],
                    "kelas": p["kelas"] or "",
                    "participant": dict(p),
                    "assessment_id": assessment["id"] if assessment else None,
                    "status": state,
                    "locked_at": assessment["locked_at"] if assessment else None,
                    "units_passed": len(result.get("unit_passed", [])) if result else 0,
                    "units_total": len(result.get("unit_results", [])) if result else 0,
                    "average_percent": result.get("average_percent") if result else None,
                    "predicate": result.get("predicate") if result else None,
                    "outcome": result.get("outcome") if result else None,
                    "outcome_label": result.get("outcome_label") if result else None,
                    "result": (
                        {
                            "outcome": result.get("outcome"),
                            "outcome_label": result.get("outcome_label"),
                            "predicate": result.get("predicate"),
                            "average_percent": result.get("average_percent"),
                            "unit_passed_count": len(result.get("unit_passed", [])),
                            "unit_total_count": len(result.get("unit_results", [])),
                            "statement": result.get("statement"),
                        }
                        if result
                        else None
                    ),
                }
            )

    unit_analytics = []
    for item in unit_stats.values():
        assessed = item["assessed_count"]
        pass_rate = round((item["passed_count"] / assessed) * 100, 2) if assessed else 0.0
        avg_pct = round(item["sum_percent"] / assessed, 2) if assessed else 0.0
        unit_analytics.append(
            {
                "kode": item["kode"],
                "judul": item["judul"],
                "scheme_kode": item["scheme_kode"],
                "assessed_count": assessed,
                "passed_count": item["passed_count"],
                "pass_rate": pass_rate,
                "pass_rate_percent": pass_rate,
                "avg_percent": avg_pct,
                "avg_score_percent": avg_pct,
            }
        )

    totals = dict(status_counts)
    return {
        "generated_at": db.utcnow(),
        "filter": {"scheme_kode": scheme_kode or "all", "school_id": school_id},
        "schools_count": len(schools),
        "totals": totals,
        "status_counts": status_counts,
        "outcomes": outcomes,
        "predicates": predicates,
        "unit_analytics": unit_analytics,
        "participant_rows": rows,
        "rows": rows,
    }
