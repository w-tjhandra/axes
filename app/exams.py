"""Exam periods, participant enrollment, archives, and certificate workflows."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

try:
    from . import db
except ImportError:  # pragma: no cover
    import db  # type: ignore[no-redef]

MAX_DOCX_BYTES = 10 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED = 100 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024
REQUIRED_CERTIFICATE_FIELDS = {
    "participant_name",
    "participant_number",
    "school_name",
    "exam_title",
    "exam_year",
    "scheme_name",
    "outcome_label",
    "certificate_number",
    "issued_date",
}
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("w", W_NS)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("", R_NS)


class ExamCreate(BaseModel):
    title: str
    year: int
    starts_on: date | None = None
    ends_on: date | None = None
    notes: str = ""
    school_ids: list[int] = Field(default_factory=list)
    scheme_kodes: list[str] = Field(default_factory=list)


class ExamPatch(BaseModel):
    title: str | None = None
    year: int | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: str | None = None
    school_ids: list[int] | None = None
    scheme_kodes: list[str] | None = None


class EnrollmentCreate(BaseModel):
    participant_id: int
    scheme_kode: str
    group_label: str = ""


class EnrollmentBatchCreate(BaseModel):
    school_id: int
    scheme_kode: str
    participant_ids: list[int] | None = None
    kelas: str | None = None
    group_label: str = ""


class EnrollmentPatch(BaseModel):
    group_label: str


class CertificateGenerate(BaseModel):
    template_id: int | None = None
    reissue: bool = False


def fail(status: int, code: str, **extra: Any) -> None:
    raise HTTPException(status_code=status, detail={"error": code, **extra})


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _date_range_ok(starts_on: date | None, ends_on: date | None) -> bool:
    return starts_on is None or ends_on is None or ends_on >= starts_on


def _resolve_exam(conn: sqlite3.Connection, exam_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM exam WHERE id = ?", (exam_id,)).fetchone()
    if row is None:
        fail(404, "exam_not_found")
    return row


def _exam_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["schools"] = [
        dict(item)
        for item in conn.execute(
            """SELECT s.id, s.kode, s.nama, s.scheme_kode FROM exam_school es
               JOIN school s ON s.id = es.school_id
               WHERE es.exam_id = ? ORDER BY s.nama""",
            (row["id"],),
        )
    ]
    result["schemes"] = [
        dict(item)
        for item in conn.execute(
            """SELECT sc.kode, sc.nama FROM exam_scheme es
               JOIN scheme sc ON sc.kode = es.scheme_kode
               WHERE es.exam_id = ? ORDER BY sc.nama""",
            (row["id"],),
        )
    ]
    result["enrollment_count"] = conn.execute(
        "SELECT COUNT(*) FROM exam_enrollment WHERE exam_id = ? AND status = 'enrolled'",
        (row["id"],),
    ).fetchone()[0]
    result["assessment_in_progress"] = conn.execute(
        """SELECT COUNT(*) FROM assessment a
           JOIN exam_enrollment ee ON ee.id = a.exam_enrollment_id
           WHERE ee.exam_id = ? AND a.status = 'in_progress'""",
        (row["id"],),
    ).fetchone()[0]
    return result


def _assert_associations(
    conn: sqlite3.Connection, school_ids: list[int], scheme_kodes: list[str]
) -> None:
    school_ids = sorted(set(school_ids))
    scheme_kodes = sorted(set(scheme_kodes))
    for school_id in school_ids:
        if conn.execute("SELECT 1 FROM school WHERE id = ?", (school_id,)).fetchone() is None:
            fail(400, "school_not_found", school_id=school_id)
    for kode in scheme_kodes:
        if conn.execute("SELECT 1 FROM scheme WHERE kode = ?", (kode,)).fetchone() is None:
            fail(400, "scheme_not_found", scheme_kode=kode)
    for school_id in school_ids:
        school_scheme = conn.execute(
            "SELECT scheme_kode FROM school WHERE id = ?", (school_id,)
        ).fetchone()["scheme_kode"]
        if scheme_kodes and school_scheme not in scheme_kodes:
            fail(
                400,
                "school_scheme_not_selected",
                school_id=school_id,
                scheme_kode=school_scheme,
            )


def _set_associations(
    conn: sqlite3.Connection, exam_id: int, school_ids: list[int], scheme_kodes: list[str]
) -> None:
    _assert_associations(conn, school_ids, scheme_kodes)
    conn.execute("DELETE FROM exam_school WHERE exam_id = ?", (exam_id,))
    conn.execute("DELETE FROM exam_scheme WHERE exam_id = ?", (exam_id,))
    conn.executemany(
        "INSERT INTO exam_school(exam_id, school_id) VALUES (?, ?)",
        [(exam_id, school_id) for school_id in sorted(set(school_ids))],
    )
    conn.executemany(
        "INSERT INTO exam_scheme(exam_id, scheme_kode) VALUES (?, ?)",
        [(exam_id, kode) for kode in sorted(set(scheme_kodes))],
    )


def _enrollment_row(conn: sqlite3.Connection, enrollment_id: int) -> sqlite3.Row:
    row = conn.execute(
        """SELECT ee.*, e.title AS exam_title, e.year AS exam_year, e.status AS exam_status,
               e.starts_on, e.ends_on, e.status AS exam_status,
                  e.starts_on, e.ends_on,
                  sc.nama AS scheme_name, s.nama AS school_name,
                  a.id AS assessment_id, a.status AS assessment_status,
                  a.locked_at, a.result_json
           FROM exam_enrollment ee
           JOIN exam e ON e.id = ee.exam_id
           JOIN scheme sc ON sc.kode = ee.scheme_kode
           JOIN school s ON s.id = ee.school_id
           LEFT JOIN assessment a ON a.exam_enrollment_id = ee.id
           WHERE ee.id = ?""",
        (enrollment_id,),
    ).fetchone()
    if row is None:
        fail(404, "enrollment_not_found")
    return row


def _enrollment_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    result = json.loads(row["result_json"]) if row["result_json"] else None
    item["result"] = (
        {
            "outcome": result.get("outcome"),
            "outcome_label": result.get("outcome_label"),
            "predicate": result.get("predicate"),
        }
        if result
        else None
    )
    item.pop("result_json", None)
    return item


def _enrollment_query(
    conn: sqlite3.Connection,
    exam_id: int,
    school_id: int | None = None,
    scheme_kode: str | None = None,
    group_label: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[sqlite3.Row], int]:
    clauses = ["ee.exam_id = ?"]
    values: list[Any] = [exam_id]
    for clause, value in (
        ("ee.school_id = ?", school_id),
        ("ee.scheme_kode = ?", scheme_kode),
        ("ee.group_label = ?", _clean(group_label) if group_label else None),
        ("ee.status = ?", status),
    ):
        if value is not None:
            clauses.append(clause)
            values.append(value)
    where = " AND ".join(clauses)
    total = conn.execute(
        f"SELECT COUNT(*) FROM exam_enrollment ee WHERE {where}", values
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT ee.*, e.title AS exam_title, e.year AS exam_year,
                   e.status AS exam_status, sc.nama AS scheme_name, s.nama AS school_name,
                   a.id AS assessment_id, a.status AS assessment_status,
                   a.locked_at, a.result_json,
                   ci.id AS certificate_id, ci.certificate_number
            FROM exam_enrollment ee
            JOIN exam e ON e.id = ee.exam_id
            JOIN scheme sc ON sc.kode = ee.scheme_kode
            JOIN school s ON s.id = ee.school_id
            LEFT JOIN assessment a ON a.exam_enrollment_id = ee.id
            LEFT JOIN certificate_issue ci ON ci.id = (
              SELECT id FROM certificate_issue
              WHERE enrollment_id = ee.id AND status = 'active'
              ORDER BY id DESC LIMIT 1
            )
            WHERE {where}
            ORDER BY s.nama, ee.group_label, ee.snapshot_number, ee.id
            LIMIT ? OFFSET ?""",
        (*values, limit, offset),
    ).fetchall()
    return rows, total


def _exam_summary(rows: list[sqlite3.Row]) -> dict[str, Any]:
    stats = {
        "total": 0,
        "assessed": 0,
        "not_started": 0,
        "in_progress": 0,
        "passed": 0,
        "failed": 0,
        "outcomes": {
            "kompeten_penuh": 0,
            "kompeten_sub": 0,
            "kompeten_unit": 0,
            "belum_kompeten": 0,
        },
    }
    for row in rows:
        if row["status"] != "enrolled":
            continue
        stats["total"] += 1
        if row["assessment_status"] == "locked" and row["result_json"]:
            stats["assessed"] += 1
            result = json.loads(row["result_json"])
            outcome = result.get("outcome")
            if outcome in stats["outcomes"]:
                stats["outcomes"][outcome] += 1
                if outcome == "belum_kompeten":
                    stats["failed"] += 1
                else:
                    stats["passed"] += 1
        elif row["assessment_status"] == "in_progress":
            stats["in_progress"] += 1
        else:
            stats["not_started"] += 1
    denominator = stats["assessed"]
    stats["pass_percent"] = round(stats["passed"] * 100 / denominator, 2) if denominator else None
    stats["fail_percent"] = round(stats["failed"] * 100 / denominator, 2) if denominator else None
    stats["completion_percent"] = round(stats["assessed"] * 100 / stats["total"], 2) if stats["total"] else 0
    stats["result_denominator"] = denominator
    return stats


def _assessments_archived(conn: sqlite3.Connection, assessment_id: int) -> bool:
    row = conn.execute(
        """SELECT e.status FROM assessment a
           JOIN exam_enrollment ee ON ee.id = a.exam_enrollment_id
           JOIN exam e ON e.id = ee.exam_id
           WHERE a.id = ?""",
        (assessment_id,),
    ).fetchone()
    return bool(row and row["status"] == "archived")


def _certificate_dir(db_path: Path) -> Path:
    target = Path(os.environ.get("CERTIFICATE_DIR", str(db_path.parent / "certificates"))).expanduser().resolve()
    static_dir = (Path(__file__).resolve().parent / "static").resolve()
    if target == static_dir or static_dir in target.parents:
        raise RuntimeError("CERTIFICATE_DIR must be outside the public static directory")
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        target.chmod(0o700)
    except OSError:
        pass
    return target


def _validate_docx(raw: bytes) -> tuple[list[str], bytes]:
    if not raw or len(raw) > MAX_DOCX_BYTES:
        fail(413 if len(raw) > MAX_DOCX_BYTES else 400, "template_size_invalid", max_bytes=MAX_DOCX_BYTES)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        infos = archive.infolist()
        names = {item.filename for item in infos}
        if (
            len(infos) > 2000
            or len(names) != len(infos)
            or sum(item.file_size for item in infos) > MAX_DOCX_UNCOMPRESSED
        ):
            fail(400, "template_archive_too_large")
        if any(item.file_size > 0 and item.file_size / max(item.compress_size, 1) > 200 for item in infos):
            fail(400, "template_compression_ratio_exceeded")
        if any((item.external_attr >> 16) & 0o170000 == 0o120000 for item in infos):
            fail(400, "template_symlink_not_allowed")
        for item in infos:
            member = PurePosixPath(item.filename)
            if member.is_absolute() or ".." in member.parts or "\\" in item.filename:
                fail(400, "template_invalid_path")
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            fail(400, "invalid_docx")
        content_types = archive.read("[Content_Types].xml")
        if b"macroEnabled" in content_types or any(name.endswith("vbaProject.bin") for name in names):
            fail(400, "macro_document_not_allowed")
        xml_parts = [name for name in names if name.startswith("word/") and name.endswith(".xml")]
        texts: list[str] = []
        for name in xml_parts:
            root = ET.fromstring(archive.read(name))
            texts.extend(element.text or "" for element in root.iter(f"{{{W_NS}}}t"))
        raw_xml = "\n".join(texts)
        # Word can split a placeholder across adjacent runs; collect text per paragraph.
        for name in xml_parts:
            root = ET.fromstring(archive.read(name))
            texts.extend(
                "".join(node.text or "" for node in paragraph.iter(f"{{{W_NS}}}t"))
                for paragraph in root.iter(f"{{{W_NS}}}p")
            )
        placeholders = sorted(set(PLACEHOLDER_PATTERN.findall(raw_xml + "\n" + "\n".join(texts))))
        missing = sorted(REQUIRED_CERTIFICATE_FIELDS - set(placeholders))
        if missing:
            fail(400, "required_placeholders_missing", placeholders=missing)
        unknown = sorted(set(placeholders) - REQUIRED_CERTIFICATE_FIELDS - {"participant_class", "exam_date", "predicate"})
        if unknown:
            fail(400, "unknown_placeholders", placeholders=unknown)
        return placeholders, raw
    except HTTPException:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError):
        fail(400, "invalid_docx")


def _replace_paragraph_placeholders(paragraph: ET.Element, values: dict[str, str]) -> None:
    nodes = list(paragraph.iter(f"{{{W_NS}}}t"))
    if not nodes:
        return
    texts = [node.text or "" for node in nodes]
    combined = "".join(texts)
    matches = list(PLACEHOLDER_PATTERN.finditer(combined))
    for match in reversed(matches):
        key = match.group(1)
        if key not in values:
            fail(400, "unknown_placeholder", placeholder=key)
        start, end = match.span()
        cursor = 0
        start_node = end_node = 0
        start_offset = end_offset = 0
        for index, text in enumerate(texts):
            next_cursor = cursor + len(text)
            if cursor <= start < next_cursor or (start == next_cursor and index == len(texts) - 1):
                start_node, start_offset = index, start - cursor
            if cursor < end <= next_cursor:
                end_node, end_offset = index, end - cursor
                break
            cursor = next_cursor
        if start_node == end_node:
            texts[start_node] = texts[start_node][:start_offset] + values[key] + texts[start_node][end_offset:]
        else:
            texts[start_node] = texts[start_node][:start_offset] + values[key]
            for index in range(start_node + 1, end_node):
                texts[index] = ""
            texts[end_node] = texts[end_node][end_offset:]
    for node, text in zip(nodes, texts):
        node.text = text
        if text.startswith(" ") or text.endswith(" "):
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _render_docx(raw: bytes, values: dict[str, str], output_path: Path) -> None:
    sanitized = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(sanitized, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename.endswith(".rels"):
                    root = ET.fromstring(data)
                    for rel in list(root):
                        if rel.attrib.get("TargetMode", "").lower() == "external":
                            root.remove(rel)
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                elif info.filename.startswith("word/") and info.filename.endswith(".xml"):
                    root = ET.fromstring(data)
                    for paragraph in root.iter(f"{{{W_NS}}}p"):
                        _replace_paragraph_placeholders(paragraph, values)
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(info, data)
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        fail(400, "invalid_docx")
    output_path.write_bytes(sanitized.getvalue())


def _convert_docx_to_pdf(docx_path: Path, work_dir: Path) -> bytes:
    converter = shutil.which(os.environ.get("CERTIFICATE_CONVERTER", "libreoffice"))
    bwrap = shutil.which("bwrap")
    if not converter or not bwrap:
        fail(
            503,
            "certificate_converter_unavailable",
            message="LibreOffice dan bubblewrap diperlukan untuk konversi DOCX terisolasi.",
        )
    (work_dir / "home").mkdir(exist_ok=True, mode=0o700)
    (work_dir / "profile").mkdir(exist_ok=True, mode=0o700)
    command = [
        bwrap,
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
    ]
    for system_path in ("/lib", "/lib64"):
        if Path(system_path).exists():
            command.extend(["--ro-bind", system_path, system_path])
    command.extend(
        [
            "--dir",
            "/etc",
            "--dir",
            "/etc/libreoffice",
            "--dir",
            "/etc/libreoffice/registry",
        ]
    )
    for system_path in (
        "/etc/ld.so.cache",
        "/etc/fonts",
        "/etc/passwd",
        "/etc/group",
        "/etc/localtime",
        "/etc/nsswitch.conf",
    ):
        if Path(system_path).exists():
            command.extend(["--ro-bind", system_path, system_path])
    registry = Path("/etc/libreoffice/registry/main.xcd")
    if registry.is_file():
        command.extend(["--ro-bind", str(registry), str(registry)])
    command.extend(
        [
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/work",
            "--bind",
            str(work_dir),
            "/work",
            "--setenv",
            "HOME",
            "/work/home",
            "--chdir",
            "/work",
            "--",
            converter,
            "-env:UserInstallation=file:///work/profile",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            "/work",
            "/work/source.docx",
        ]
    )
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(work_dir / "home")},
        )
    except subprocess.TimeoutExpired:
        fail(504, "certificate_conversion_timeout")
    except OSError as exc:
        fail(503, "certificate_conversion_failed", message=str(exc)[:200])
    pdf_path = work_dir / "source.pdf"
    if process.returncode != 0 or not pdf_path.is_file():
        fail(502, "certificate_conversion_failed", message=(process.stderr or process.stdout or "")[-500:])
    if pdf_path.stat().st_size > MAX_PDF_BYTES:
        fail(413, "certificate_pdf_too_large", max_bytes=MAX_PDF_BYTES)
    pdf = pdf_path.read_bytes()
    if not pdf.startswith(b"%PDF-"):
        fail(502, "certificate_conversion_invalid_pdf")
    return pdf


def _template_bytes(conn: sqlite3.Connection, template_id: int, storage: Path) -> tuple[sqlite3.Row, bytes]:
    row = conn.execute("SELECT * FROM certificate_template WHERE id = ?", (template_id,)).fetchone()
    if row is None:
        fail(404, "certificate_template_not_found")
    path = (storage / row["storage_key"]).resolve()
    if path.parent != storage or not path.is_file():
        fail(404, "certificate_template_file_missing")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        fail(500, "certificate_template_read_failed", message=str(exc)[:200])
    if hashlib.sha256(raw).hexdigest() != row["checksum"]:
        fail(500, "certificate_template_integrity_failed")
    return row, raw


def _pick_template(
    conn: sqlite3.Connection, enrollment: sqlite3.Row, explicit_id: int | None
) -> sqlite3.Row:
    if explicit_id:
        row = conn.execute(
            "SELECT * FROM certificate_template WHERE id = ? AND active = 1", (explicit_id,)
        ).fetchone()
        if row is None:
            fail(404, "active_certificate_template_not_found")
        if row["exam_id"] not in (None, enrollment["exam_id"]) or row["scheme_kode"] not in (
            None,
            enrollment["scheme_kode"],
        ):
            fail(400, "certificate_template_scope_mismatch")
        return row
    row = conn.execute(
        """SELECT * FROM certificate_template
           WHERE active = 1 AND exam_id = ? AND scheme_kode = ?
           ORDER BY version DESC LIMIT 1""",
        (enrollment["exam_id"], enrollment["scheme_kode"]),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """SELECT * FROM certificate_template
               WHERE active = 1 AND exam_id = ? AND scheme_kode IS NULL
               ORDER BY version DESC LIMIT 1""",
            (enrollment["exam_id"],),
        ).fetchone()
    if row is None:
        row = conn.execute(
            """SELECT * FROM certificate_template
               WHERE active = 1 AND exam_id IS NULL AND scheme_kode = ?
               ORDER BY version DESC LIMIT 1""",
            (enrollment["scheme_kode"],),
        ).fetchone()
    if row is None:
        fail(409, "active_certificate_template_missing")
    return row


def _certificate_values(enrollment: sqlite3.Row, result: dict[str, Any], number: str) -> dict[str, str]:
    exam_date = " – ".join(value for value in (enrollment["starts_on"], enrollment["ends_on"]) if value)
    return {
        "participant_name": enrollment["snapshot_name"],
        "participant_number": enrollment["snapshot_number"],
        "participant_class": enrollment["group_label"] or enrollment["snapshot_class"],
        "school_name": enrollment["snapshot_school_name"],
        "exam_title": enrollment["exam_title"],
        "exam_year": str(enrollment["exam_year"]),
        "exam_date": exam_date,
        "scheme_name": enrollment["scheme_name"],
        "outcome_label": result.get("outcome_label") or result.get("outcome") or "",
        "predicate": result.get("predicate") or "",
        "certificate_number": number,
        "issued_date": date.today().isoformat(),
    }


def _safe_download_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (cleaned[:100] or "sertifikat") + ".pdf"


def register_routes(app: FastAPI, auth_ctx: Any) -> None:
    @app.get("/api/exams")
    def list_exams(
        year: int | None = None,
        status: str | None = None,
        search: str | None = None,
        school_id: int | None = None,
        scheme_kode: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        clauses: list[str] = []
        values: list[Any] = []
        if year is not None:
            clauses.append("e.year = ?")
            values.append(year)
        if status:
            if status not in {"draft", "active", "closed", "archived"}:
                fail(400, "invalid_exam_status")
            clauses.append("e.status = ?")
            values.append(status)
        if search:
            clauses.append("e.title LIKE ?")
            values.append(f"%{search.strip()}%")
        if school_id is not None:
            clauses.append("EXISTS (SELECT 1 FROM exam_school es WHERE es.exam_id=e.id AND es.school_id=?)")
            values.append(school_id)
        if scheme_kode:
            clauses.append("EXISTS (SELECT 1 FROM exam_scheme es WHERE es.exam_id=e.id AND es.scheme_kode=?)")
            values.append(scheme_kode)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = conn.execute(f"SELECT COUNT(*) FROM exam e {where}", values).fetchone()[0]
        rows = conn.execute(
            f"SELECT e.* FROM exam e {where} ORDER BY e.year DESC, e.id DESC LIMIT ? OFFSET ?",
            (*values, limit, offset),
        ).fetchall()
        return {"data": [_exam_payload(conn, row) for row in rows], "meta": {"total": total, "limit": limit, "offset": offset}}

    @app.post("/api/exams", status_code=201)
    def create_exam(body: ExamCreate, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        title = _clean(body.title)
        if not title or len(title) > 160 or not 2000 <= body.year <= 2200:
            fail(400, "invalid_exam", message="Judul wajib (maksimal 160 karakter) dan tahun harus 2000–2200.")
        if not _date_range_ok(body.starts_on, body.ends_on):
            fail(400, "invalid_exam_date_range")
        if conn.execute(
            "SELECT 1 FROM exam WHERE year=? AND lower(trim(title))=lower(trim(?))",
            (body.year, title),
        ).fetchone():
            fail(409, "exam_title_year_exists")
        _assert_associations(conn, body.school_ids, body.scheme_kodes)
        now = db.utcnow()
        cursor = conn.execute(
            """INSERT INTO exam(title, year, starts_on, ends_on, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                body.year,
                body.starts_on.isoformat() if body.starts_on else None,
                body.ends_on.isoformat() if body.ends_on else None,
                _clean(body.notes),
                now,
                now,
            ),
        )
        exam_id = cursor.lastrowid
        _set_associations(conn, exam_id, body.school_ids, body.scheme_kodes)
        db.audit(conn, user["id"], "exam_create", "exam", exam_id, new_value={"title": title, "year": body.year})
        conn.commit()
        return _exam_payload(conn, _resolve_exam(conn, exam_id))

    @app.get("/api/exams/dashboard")
    def exam_dashboard(
        exam_id: str | None = None,
        school_id: int | None = None,
        scheme_kode: str | None = None,
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        selected_exam: sqlite3.Row | None
        if exam_id and exam_id != "all":
            if not exam_id.isdigit():
                fail(400, "invalid_exam_id")
            selected_exam = _resolve_exam(conn, int(exam_id))
        elif exam_id == "all":
            selected_exam = None
        else:
            selected_exam = conn.execute(
                "SELECT * FROM exam WHERE status='active' ORDER BY year DESC, id DESC LIMIT 1"
            ).fetchone()
            if selected_exam is None:
                selected_exam = conn.execute(
                    "SELECT * FROM exam WHERE status IN ('closed','archived') ORDER BY year DESC, id DESC LIMIT 1"
                ).fetchone()
        clauses = ["ee.status = 'enrolled'"]
        values: list[Any] = []
        if selected_exam:
            clauses.append("ee.exam_id = ?")
            values.append(selected_exam["id"])
        if school_id is not None:
            clauses.append("ee.school_id = ?")
            values.append(school_id)
        if scheme_kode:
            clauses.append("ee.scheme_kode = ?")
            values.append(scheme_kode)
        rows = conn.execute(
            f"""SELECT ee.status, a.status AS assessment_status, a.result_json
                FROM exam_enrollment ee
                LEFT JOIN assessment a ON a.exam_enrollment_id=ee.id
                WHERE {' AND '.join(clauses)}""",
            values,
        ).fetchall()
        stats = _exam_summary(rows)
        exams = conn.execute(
            """SELECT id, title, year, status FROM exam
               WHERE status != 'archived' ORDER BY year DESC, id DESC"""
        ).fetchall()
        schools = conn.execute(
            """SELECT DISTINCT s.id, s.nama FROM school s JOIN exam_school es ON es.school_id=s.id
               WHERE (? IS NULL OR es.exam_id=?) ORDER BY s.nama""",
            (selected_exam["id"] if selected_exam else None, selected_exam["id"] if selected_exam else None),
        ).fetchall()
        schemes = conn.execute(
            """SELECT DISTINCT sc.kode, sc.nama FROM scheme sc
               JOIN exam_scheme es ON es.scheme_kode=sc.kode
               WHERE (? IS NULL OR es.exam_id=?) ORDER BY sc.nama""",
            (selected_exam["id"] if selected_exam else None, selected_exam["id"] if selected_exam else None),
        ).fetchall()
        return {
            "exam": dict(selected_exam) if selected_exam else None,
            "stats": stats,
            "exams": [dict(row) for row in exams],
            "schools": [dict(row) for row in schools],
            "schemes": [dict(row) for row in schemes],
        }

    @app.get("/api/exams/{exam_id}")
    def get_exam(exam_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        return _exam_payload(conn, _resolve_exam(conn, exam_id))

    @app.patch("/api/exams/{exam_id}")
    def patch_exam(exam_id: int, body: ExamPatch, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = _resolve_exam(conn, exam_id)
        if row["status"] in {"closed", "archived"}:
            fail(409, "exam_not_editable")
        changes = body.model_dump(exclude_unset=True)
        title = _clean(changes.get("title", row["title"]))
        year = changes.get("year", row["year"])
        starts = changes.get("starts_on", date.fromisoformat(row["starts_on"]) if row["starts_on"] else None)
        ends = changes.get("ends_on", date.fromisoformat(row["ends_on"]) if row["ends_on"] else None)
        if not title or len(title) > 160 or not isinstance(year, int) or not 2000 <= year <= 2200:
            fail(400, "invalid_exam")
        if not _date_range_ok(starts, ends):
            fail(400, "invalid_exam_date_range")
        if conn.execute(
            "SELECT 1 FROM exam WHERE id != ? AND year=? AND lower(trim(title))=lower(trim(?))",
            (exam_id, year, title),
        ).fetchone():
            fail(409, "exam_title_year_exists")
        if "school_ids" in changes or "scheme_kodes" in changes:
            old_schools = [r[0] for r in conn.execute("SELECT school_id FROM exam_school WHERE exam_id=?", (exam_id,))]
            old_schemes = [r[0] for r in conn.execute("SELECT scheme_kode FROM exam_scheme WHERE exam_id=?", (exam_id,))]
            schools = changes.get("school_ids", old_schools)
            schemes = changes.get("scheme_kodes", old_schemes)
            used = conn.execute(
                "SELECT COUNT(*) FROM exam_enrollment WHERE exam_id=? AND status='enrolled'",
                (exam_id,),
            ).fetchone()[0]
            if used and (set(old_schools) - set(schools) or set(old_schemes) - set(schemes)):
                fail(409, "exam_association_in_use")
            _set_associations(conn, exam_id, schools, schemes)
        old_value = dict(row)
        conn.execute(
            """UPDATE exam SET title=?, year=?, starts_on=?, ends_on=?, notes=?, updated_at=?
               WHERE id=?""",
            (
                title,
                year,
                starts.isoformat() if starts else None,
                ends.isoformat() if ends else None,
                _clean(changes.get("notes", row["notes"])),
                db.utcnow(),
                exam_id,
            ),
        )
        db.audit(
            conn,
            user["id"],
            "exam_update",
            "exam",
            exam_id,
            old_value,
            body.model_dump(mode="json", exclude_unset=True),
        )
        conn.commit()
        return _exam_payload(conn, _resolve_exam(conn, exam_id))

    @app.post("/api/exams/{exam_id}/activate")
    def activate_exam(exam_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = _resolve_exam(conn, exam_id)
        if row["status"] != "draft":
            fail(409, "invalid_exam_transition", from_status=row["status"], to_status="active")
        if not conn.execute("SELECT 1 FROM exam_school WHERE exam_id=?", (exam_id,)).fetchone():
            fail(400, "exam_school_required")
        if not conn.execute("SELECT 1 FROM exam_scheme WHERE exam_id=?", (exam_id,)).fetchone():
            fail(400, "exam_scheme_required")
        now = db.utcnow()
        conn.execute("UPDATE exam SET status='active', updated_at=? WHERE id=?", (now, exam_id))
        db.audit(conn, user["id"], "exam_activate", "exam", exam_id, {"status": "draft"}, {"status": "active"})
        conn.commit()
        return _exam_payload(conn, _resolve_exam(conn, exam_id))

    @app.post("/api/exams/{exam_id}/close")
    def close_exam(exam_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = _resolve_exam(conn, exam_id)
        if row["status"] != "active":
            fail(409, "invalid_exam_transition", from_status=row["status"], to_status="closed")
        now = db.utcnow()
        conn.execute("UPDATE exam SET status='closed', updated_at=? WHERE id=?", (now, exam_id))
        db.audit(conn, user["id"], "exam_close", "exam", exam_id, {"status": "active"}, {"status": "closed"})
        conn.commit()
        return _exam_payload(conn, _resolve_exam(conn, exam_id))

    @app.post("/api/exams/{exam_id}/archive")
    def archive_exam(exam_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = _resolve_exam(conn, exam_id)
        if row["status"] not in {"active", "closed"}:
            fail(409, "invalid_exam_transition", from_status=row["status"], to_status="archived")
        unfinished = conn.execute(
            """SELECT ee.id, ee.snapshot_name, ee.snapshot_number FROM exam_enrollment ee
               JOIN assessment a ON a.exam_enrollment_id=ee.id
               WHERE ee.exam_id=? AND a.status='in_progress' ORDER BY ee.id LIMIT 100""",
            (exam_id,),
        ).fetchall()
        if unfinished:
            fail(
                409,
                "exam_has_unfinished_assessments",
                count=conn.execute(
                    """SELECT COUNT(*) FROM exam_enrollment ee
                       JOIN assessment a ON a.exam_enrollment_id=ee.id
                       WHERE ee.exam_id=? AND a.status='in_progress'""",
                    (exam_id,),
                ).fetchone()[0],
                participants=[dict(item) for item in unfinished],
            )
        now = db.utcnow()
        conn.execute(
            "UPDATE exam SET status='archived', archived_at=?, updated_at=? WHERE id=?",
            (now, now, exam_id),
        )
        db.audit(conn, user["id"], "exam_archive", "exam", exam_id, {"status": row["status"]}, {"status": "archived"})
        conn.commit()
        return _exam_payload(conn, _resolve_exam(conn, exam_id))

    @app.get("/api/archives/exams")
    def list_archived_exams(
        search: str | None = None,
        year: int | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        clauses = ["status='archived'"]
        values: list[Any] = []
        if search:
            clauses.append("title LIKE ?")
            values.append(f"%{search.strip()}%")
        if year:
            clauses.append("year=?")
            values.append(year)
        where = " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM exam WHERE {where}", values).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM exam WHERE {where} ORDER BY year DESC, id DESC LIMIT ? OFFSET ?",
            (*values, limit, offset),
        ).fetchall()
        return {"data": [_exam_payload(conn, row) for row in rows], "meta": {"total": total, "limit": limit, "offset": offset}}

    @app.get("/api/exams/{exam_id}/enrollments")
    def list_enrollments(
        exam_id: int,
        school_id: int | None = None,
        scheme_kode: str | None = None,
        group_label: str | None = None,
        status: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        _resolve_exam(conn, exam_id)
        if status not in (None, "enrolled", "withdrawn"):
            fail(400, "invalid_enrollment_status")
        rows, total = _enrollment_query(
            conn, exam_id, school_id, scheme_kode, group_label, status, limit, offset
        )
        return {
            "data": [_enrollment_payload(row) for row in rows],
            "meta": {"total": total, "limit": limit, "offset": offset},
        }

    @app.post("/api/exams/{exam_id}/enrollments", status_code=201)
    def create_enrollment(exam_id: int, body: EnrollmentCreate, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        exam = _resolve_exam(conn, exam_id)
        if exam["status"] not in {"draft", "active"}:
            fail(409, "exam_roster_closed")
        participant = conn.execute(
            """SELECT p.*, s.nama AS school_name, s.scheme_kode AS school_scheme
               FROM participant p JOIN school s ON s.id=p.school_id WHERE p.id=?""",
            (body.participant_id,),
        ).fetchone()
        if participant is None:
            fail(404, "participant_not_found")
        if conn.execute(
            "SELECT 1 FROM exam_school WHERE exam_id=? AND school_id=?",
            (exam_id, participant["school_id"]),
        ).fetchone() is None:
            fail(400, "school_not_associated")
        if conn.execute(
            "SELECT 1 FROM exam_scheme WHERE exam_id=? AND scheme_kode=?",
            (exam_id, body.scheme_kode),
        ).fetchone() is None:
            fail(400, "scheme_not_associated")
        if body.scheme_kode != participant["school_scheme"]:
            fail(400, "school_scheme_mismatch", scheme_kode=participant["school_scheme"])
        if conn.execute(
            "SELECT 1 FROM exam_enrollment WHERE exam_id=? AND participant_id=? AND scheme_kode=?",
            (exam_id, participant["id"], body.scheme_kode),
        ).fetchone():
            fail(409, "enrollment_exists")
        now = db.utcnow()
        cursor = conn.execute(
            """INSERT INTO exam_enrollment
               (exam_id, participant_id, school_id, scheme_kode, group_label,
                snapshot_number, snapshot_name, snapshot_class, snapshot_school_name,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                exam_id,
                participant["id"],
                participant["school_id"],
                body.scheme_kode,
                _clean(body.group_label),
                participant["nomor"],
                participant["nama"],
                participant["kelas"] or "",
                participant["school_name"],
                now,
                now,
            ),
        )
        enrollment_id = cursor.lastrowid
        db.audit(
            conn,
            user["id"],
            "enrollment_create",
            "exam_enrollment",
            enrollment_id,
            new_value={"exam_id": exam_id, "participant_id": participant["id"], "scheme_kode": body.scheme_kode},
        )
        conn.commit()
        return _enrollment_payload(_enrollment_row(conn, enrollment_id))

    @app.post("/api/exams/{exam_id}/enrollments/batch", status_code=201)
    def create_enrollment_batch(exam_id: int, body: EnrollmentBatchCreate, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        exam = _resolve_exam(conn, exam_id)
        if exam["status"] not in {"draft", "active"}:
            fail(409, "exam_roster_closed")
        school = conn.execute("SELECT * FROM school WHERE id=?", (body.school_id,)).fetchone()
        if school is None:
            fail(404, "school_not_found")
        if conn.execute(
            "SELECT 1 FROM exam_school WHERE exam_id=? AND school_id=?",
            (exam_id, body.school_id),
        ).fetchone() is None:
            fail(400, "school_not_associated")
        if conn.execute(
            "SELECT 1 FROM exam_scheme WHERE exam_id=? AND scheme_kode=?",
            (exam_id, body.scheme_kode),
        ).fetchone() is None:
            fail(400, "scheme_not_associated")
        if body.scheme_kode != school["scheme_kode"]:
            fail(400, "school_scheme_mismatch", scheme_kode=school["scheme_kode"])

        if body.participant_ids is not None:
            ids = [int(pid) for pid in body.participant_ids if pid]
            if not ids:
                return {"added": 0, "skipped": 0, "total": 0}
            placeholders = ",".join("?" for _ in ids)
            participants = conn.execute(
                f"SELECT * FROM participant WHERE school_id=? AND id IN ({placeholders}) ORDER BY nomor",
                [body.school_id, *ids],
            ).fetchall()
        elif body.kelas is not None:
            participants = conn.execute(
                "SELECT * FROM participant WHERE school_id=? AND lower(trim(coalesce(kelas,''))) = lower(trim(?)) ORDER BY nomor",
                (body.school_id, body.kelas),
            ).fetchall()
        else:
            participants = conn.execute(
                "SELECT * FROM participant WHERE school_id=? ORDER BY nomor",
                (body.school_id,),
            ).fetchall()

        now = db.utcnow()
        custom_group = _clean(body.group_label)
        added = 0
        skipped = 0
        for participant in participants:
            exists = conn.execute(
                "SELECT 1 FROM exam_enrollment WHERE exam_id=? AND participant_id=? AND scheme_kode=?",
                (exam_id, participant["id"], body.scheme_kode),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            conn.execute(
                """INSERT INTO exam_enrollment
                   (exam_id, participant_id, school_id, scheme_kode, group_label,
                    snapshot_number, snapshot_name, snapshot_class, snapshot_school_name,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    exam_id,
                    participant["id"],
                    body.school_id,
                    body.scheme_kode,
                    custom_group or (participant["kelas"] or ""),
                    participant["nomor"],
                    participant["nama"],
                    participant["kelas"] or "",
                    school["nama"],
                    now,
                    now,
                ),
            )
            added += 1

        db.audit(
            conn,
            user["id"],
            "enrollment_batch_create",
            "exam",
            exam_id,
            new_value={
                "school_id": body.school_id,
                "scheme_kode": body.scheme_kode,
                "kelas": body.kelas,
                "added": added,
                "skipped": skipped,
            },
        )
        conn.commit()
        return {"added": added, "skipped": skipped, "total": len(participants)}

    @app.patch("/api/exams/{exam_id}/enrollments/{enrollment_id}")
    def patch_enrollment(
        exam_id: int, enrollment_id: int, body: EnrollmentPatch, ctx: tuple = Depends(auth_ctx)
    ):
        conn, user = ctx
        exam = _resolve_exam(conn, exam_id)
        enrollment = _enrollment_row(conn, enrollment_id)
        if enrollment["exam_id"] != exam_id:
            fail(404, "enrollment_not_found")
        if exam["status"] not in {"draft", "active"} or enrollment["status"] != "enrolled":
            fail(409, "enrollment_not_editable")
        now = db.utcnow()
        group = _clean(body.group_label)
        conn.execute(
            "UPDATE exam_enrollment SET group_label=?, updated_at=? WHERE id=?",
            (group, now, enrollment_id),
        )
        db.audit(conn, user["id"], "enrollment_update", "exam_enrollment", enrollment_id, {"group_label": enrollment["group_label"]}, {"group_label": group})
        conn.commit()
        return _enrollment_payload(_enrollment_row(conn, enrollment_id))

    @app.post("/api/exams/{exam_id}/enrollments/{enrollment_id}/withdraw")
    def withdraw_enrollment(exam_id: int, enrollment_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        exam = _resolve_exam(conn, exam_id)
        enrollment = _enrollment_row(conn, enrollment_id)
        if enrollment["exam_id"] != exam_id:
            fail(404, "enrollment_not_found")
        if exam["status"] not in {"draft", "active"} or enrollment["status"] != "enrolled":
            fail(409, "enrollment_not_withdrawable")
        if enrollment["assessment_id"] is not None:
            fail(409, "enrollment_has_assessment")
        conn.execute(
            "UPDATE exam_enrollment SET status='withdrawn', updated_at=? WHERE id=?",
            (db.utcnow(), enrollment_id),
        )
        db.audit(conn, user["id"], "enrollment_withdraw", "exam_enrollment", enrollment_id, {"status": "enrolled"}, {"status": "withdrawn"})
        conn.commit()
        return {"ok": True, "status": "withdrawn"}

    @app.post("/api/exams/{exam_id}/enrollments/import")
    async def import_enrollments(
        exam_id: int,
        school_id: int = Form(...),
        scheme_kode: str = Form(...),
        group_label: str = Form(""),
        file: UploadFile = File(...),
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, user = ctx
        exam = _resolve_exam(conn, exam_id)
        if exam["status"] not in {"draft", "active"}:
            fail(409, "exam_roster_closed")
        if conn.execute("SELECT 1 FROM exam_school WHERE exam_id=? AND school_id=?", (exam_id, school_id)).fetchone() is None:
            fail(400, "school_not_associated")
        if conn.execute("SELECT 1 FROM exam_scheme WHERE exam_id=? AND scheme_kode=?", (exam_id, scheme_kode)).fetchone() is None:
            fail(400, "scheme_not_associated")
        school = conn.execute("SELECT * FROM school WHERE id=?", (school_id,)).fetchone()
        if school is None:
            fail(404, "school_not_found")
        if school["scheme_kode"] != scheme_kode:
            fail(400, "school_scheme_mismatch")
        raw = await file.read(MAX_DOCX_BYTES + 1)
        if len(raw) > 2 * 1024 * 1024:
            fail(413, "csv_too_large", message="Ukuran file CSV maksimal 2 MB")
        text = raw.decode("utf-8-sig", errors="replace")
        if not text.strip():
            fail(400, "empty_csv")
        delimiter = ";" if text[:4096].count(";") > text[:4096].count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            fail(400, "invalid_header", required=["nomor", "nama"])
        field_map = {name.strip().lower(): name for name in reader.fieldnames if name}
        if not {"nomor", "nama"}.issubset(field_map):
            fail(400, "invalid_header", required=["nomor", "nama"], found=sorted(field_map))
        imported = 0
        created_master = 0
        errors: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        seen: set[str] = set()
        now = db.utcnow()
        for row_number, row in enumerate(reader, start=2):
            nomor = _clean(row.get(field_map["nomor"]))
            nama = _clean(row.get(field_map["nama"]))
            kelas = _clean(row.get(field_map.get("kelas", "")))
            group = _clean(row.get(field_map.get("kelompok", ""))) or _clean(group_label)
            if not nomor and not nama:
                continue
            if not nomor or not nama:
                errors.append({"row": row_number, "message": "Nomor dan nama wajib diisi"})
                continue
            if nomor in seen:
                duplicates.append({"row": row_number, "nomor": nomor, "reason": "duplikat dalam file"})
                continue
            seen.add(nomor)
            participant = conn.execute(
                "SELECT * FROM participant WHERE school_id=? AND nomor=?", (school_id, nomor)
            ).fetchone()
            if participant is None:
                cursor = conn.execute(
                    """INSERT INTO participant(school_id, nomor, nama, kelas, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (school_id, nomor, nama, kelas, now, now),
                )
                participant_id = cursor.lastrowid
                created_master += 1
            else:
                if participant["nama"] != nama:
                    errors.append({"row": row_number, "nomor": nomor, "message": "Nama berbeda dari daftar induk; data induk tidak ditimpa"})
                    continue
                participant_id = participant["id"]
                if not kelas:
                    kelas = participant["kelas"] or ""
            exists = conn.execute(
                "SELECT 1 FROM exam_enrollment WHERE exam_id=? AND participant_id=? AND scheme_kode=?",
                (exam_id, participant_id, scheme_kode),
            ).fetchone()
            if exists:
                duplicates.append({"row": row_number, "nomor": nomor, "reason": "sudah terdaftar pada ujian/skema"})
                continue
            participant = conn.execute(
                "SELECT nama, nomor, kelas FROM participant WHERE id=?", (participant_id,)
            ).fetchone()
            conn.execute(
                """INSERT INTO exam_enrollment
                   (exam_id, participant_id, school_id, scheme_kode, group_label,
                    snapshot_number, snapshot_name, snapshot_class, snapshot_school_name,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (exam_id, participant_id, school_id, scheme_kode, group, participant["nomor"],
                 participant["nama"], participant["kelas"] or "", school["nama"], now, now),
            )
            imported += 1
        db.audit(
            conn,
            user["id"],
            "enrollment_import",
            "exam",
            exam_id,
            new_value={"school_id": school_id, "scheme_kode": scheme_kode, "imported": imported, "created_master": created_master},
        )
        conn.commit()
        return {"imported": imported, "created_master": created_master, "errors": errors, "duplicates": duplicates}

    @app.get("/api/exams/{exam_id}/export")
    def export_exam(
        exam_id: int,
        format: str = "csv",
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, user = ctx
        exam = _resolve_exam(conn, exam_id)
        rows, _ = _enrollment_query(conn, exam_id, limit=100000)
        output = io.BytesIO()
        headers = ["judul_ujian", "tahun", "sekolah", "nomor", "nama", "kelas", "kelompok", "skema", "status_pendaftaran", "status_asesmen", "outcome", "locked_at"]
        values = []
        for row in rows:
            result = json.loads(row["result_json"]) if row["result_json"] else {}
            values.append([
                exam["title"], exam["year"], row["snapshot_school_name"], row["snapshot_number"],
                row["snapshot_name"], row["snapshot_class"], row["group_label"], row["scheme_kode"],
                row["status"], row["assessment_status"] or "not_started", result.get("outcome", ""),
                row["locked_at"] or "",
            ])
        if format == "xlsx":
            try:
                from openpyxl import Workbook
            except ImportError as exc:
                fail(503, "xlsx_export_unavailable", message=str(exc))
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Roster & Hasil"
            sheet.append(headers)
            for value in values:
                sheet.append(value)
            sheet.freeze_panes = "A2"
            workbook.save(output)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            suffix = "xlsx"
        elif format == "csv":
            text = io.StringIO(newline="")
            writer = csv.writer(text)
            writer.writerow(headers)
            writer.writerows(values)
            output.write(("\ufeff" + text.getvalue()).encode("utf-8"))
            media_type = "text/csv; charset=utf-8"
            suffix = "csv"
        else:
            fail(400, "unsupported_export_format", allowed=["csv", "xlsx"])
        db.audit(conn, user["id"], "exam_export", "exam", exam_id, metadata={"format": format, "rows": len(values)})
        conn.commit()
        output.seek(0)
        return StreamingResponse(
            output,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="ujian-{exam_id}.{suffix}"'},
        )

    @app.get("/api/certificate-templates")
    def list_templates(
        exam_id: int | None = None,
        scheme_kode: str | None = None,
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, _ = ctx
        clauses: list[str] = []
        values: list[Any] = []
        if exam_id is not None:
            clauses.append("(exam_id = ? OR exam_id IS NULL)")
            values.append(exam_id)
        if scheme_kode:
            clauses.append("(scheme_kode = ? OR scheme_kode IS NULL)")
            values.append(scheme_kode)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""SELECT id, exam_id, scheme_kode, version, original_name, checksum,
                       placeholders_json, active, previewed_at, created_at
                FROM certificate_template {where} ORDER BY exam_id DESC, scheme_kode, version DESC""",
            values,
        ).fetchall()
        return {
            "data": [
                {**dict(row), "placeholders": json.loads(row["placeholders_json"])}
                for row in rows
            ],
            "meta": {"total": len(rows)},
        }

    @app.get("/api/certificates/status")
    def certificate_status(ctx: tuple = Depends(auth_ctx)):
        converter = os.environ.get("CERTIFICATE_CONVERTER", "libreoffice")
        return {
            "ready": bool(shutil.which(converter) and shutil.which("bwrap")),
            "converter": Path(shutil.which(converter) or converter).name,
            "isolation": "bubblewrap-network-and-pid-namespace" if shutil.which("bwrap") else None,
            "max_template_bytes": MAX_DOCX_BYTES,
            "max_pdf_bytes": MAX_PDF_BYTES,
        }

    @app.post("/api/certificate-templates", status_code=201)
    async def upload_template(
        exam_id: int | None = Form(None),
        scheme_kode: str | None = Form(None),
        file: UploadFile = File(...),
        ctx: tuple = Depends(auth_ctx),
    ):
        conn, user = ctx
        if (exam_id is None) == (scheme_kode is None):
            fail(400, "template_scope_required", message="Pilih satu cakupan: ujian atau skema.")
        if exam_id is not None:
            exam = _resolve_exam(conn, exam_id)
            if exam["status"] == "archived":
                fail(409, "exam_archived")
        if scheme_kode and conn.execute("SELECT 1 FROM scheme WHERE kode=?", (scheme_kode,)).fetchone() is None:
            fail(404, "scheme_not_found")
        filename = Path(file.filename or "").name
        if Path(filename).suffix.lower() != ".docx":
            fail(400, "template_format_invalid", allowed=[".docx"])
        raw = await file.read(MAX_DOCX_BYTES + 1)
        placeholders, _ = _validate_docx(raw)
        storage = _certificate_dir(Path(app.state.db_path))
        key = f"template-{uuid.uuid4().hex}.docx"
        path = storage / key
        try:
            path.write_bytes(raw)
            path.chmod(0o600)
            version = conn.execute(
                """SELECT COALESCE(MAX(version), 0) + 1 FROM certificate_template
                   WHERE exam_id IS ? AND scheme_kode IS ?""",
                (exam_id, scheme_kode),
            ).fetchone()[0]
            checksum = hashlib.sha256(raw).hexdigest()
            now = db.utcnow()
            cursor = conn.execute(
                """INSERT INTO certificate_template
                   (exam_id, scheme_kode, version, original_name, storage_key, checksum,
                    placeholders_json, active, uploaded_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (exam_id, scheme_kode, version, filename[:255], key, checksum, json.dumps(placeholders), user["id"], now),
            )
            template_id = cursor.lastrowid
            db.audit(
                conn,
                user["id"],
                "certificate_template_upload",
                "certificate_template",
                template_id,
                new_value={"exam_id": exam_id, "scheme_kode": scheme_kode, "version": version, "checksum": checksum},
            )
            conn.commit()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {"id": template_id, "version": version, "placeholders": placeholders, "active": False}

    @app.post("/api/certificate-templates/{template_id}/preview")
    def preview_template(template_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        storage = _certificate_dir(Path(app.state.db_path))
        template, raw = _template_bytes(conn, template_id, storage)
        sample = {name: f"Contoh {name}" for name in json.loads(template["placeholders_json"])}
        sample.update(
            {
                "participant_name": "Contoh Peserta",
                "participant_number": "000",
                "school_name": "Contoh Sekolah",
                "exam_title": "Contoh Ujian",
                "exam_year": str(date.today().year),
                "scheme_name": "Contoh Skema",
                "outcome_label": "Kompeten",
                "certificate_number": "CONTOH-00001",
                "issued_date": date.today().isoformat(),
            }
        )
        with tempfile.TemporaryDirectory(prefix="aeroassess-preview-") as directory:
            work = Path(directory)
            _render_docx(raw, sample, work / "source.docx")
            pdf = _convert_docx_to_pdf(work / "source.docx", work)
        conn.execute("UPDATE certificate_template SET previewed_at=? WHERE id=?", (db.utcnow(), template_id))
        db.audit(conn, user["id"], "certificate_template_preview", "certificate_template", template_id)
        conn.commit()
        return StreamingResponse(
            io.BytesIO(pdf),
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="preview-sertifikat.pdf"'},
        )

    @app.post("/api/certificate-templates/{template_id}/activate")
    def activate_template(template_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM certificate_template WHERE id=?", (template_id,)).fetchone()
        if row is None:
            fail(404, "certificate_template_not_found")
        if not row["previewed_at"]:
            fail(409, "certificate_template_preview_required")
        if row["exam_id"] is not None:
            exam = _resolve_exam(conn, row["exam_id"])
            if exam["status"] == "archived":
                fail(409, "exam_archived")
        conn.execute(
            """UPDATE certificate_template SET active=0
               WHERE exam_id IS ? AND scheme_kode IS ?""",
            (row["exam_id"], row["scheme_kode"]),
        )
        conn.execute("UPDATE certificate_template SET active=1 WHERE id=?", (template_id,))
        db.audit(conn, user["id"], "certificate_template_activate", "certificate_template", template_id, new_value={"version": row["version"]})
        conn.commit()
        return {"ok": True, "id": template_id, "active": True}

    @app.get("/api/enrollments/{enrollment_id}/certificates")
    def list_certificates(enrollment_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, _ = ctx
        _enrollment_row(conn, enrollment_id)
        rows = conn.execute(
            """SELECT ci.id, ci.assessment_id, ci.template_id, ci.certificate_number,
                      ci.checksum, ci.status, ci.supersedes_id, ci.issued_at,
                      ct.version AS template_version, ct.original_name AS template_name
               FROM certificate_issue ci JOIN certificate_template ct ON ct.id=ci.template_id
               WHERE ci.enrollment_id=? ORDER BY ci.id DESC""",
            (enrollment_id,),
        ).fetchall()
        return {"data": [dict(row) for row in rows], "meta": {"total": len(rows)}}

    @app.post("/api/enrollments/{enrollment_id}/certificate", status_code=201)
    def issue_certificate(
        enrollment_id: int, body: CertificateGenerate, ctx: tuple = Depends(auth_ctx)
    ):
        conn, user = ctx
        enrollment = _enrollment_row(conn, enrollment_id)
        if enrollment["status"] != "enrolled":
            fail(409, "enrollment_not_active")
        if enrollment["exam_status"] == "archived":
            fail(409, "exam_archived")
        if enrollment["assessment_id"] is None or enrollment["assessment_status"] != "locked":
            fail(409, "assessment_not_final")
        result = json.loads(enrollment["result_json"]) if enrollment["result_json"] else {}
        if result.get("outcome") not in {"kompeten_penuh", "kompeten_sub"}:
            fail(409, "certificate_requires_passing_result")
        template = _pick_template(conn, enrollment, body.template_id)
        conn.execute("BEGIN IMMEDIATE")
        path: Path | None = None
        try:
            prior = conn.execute(
                """SELECT * FROM certificate_issue
                   WHERE enrollment_id=? AND assessment_id=? AND status='active'
                   ORDER BY id DESC LIMIT 1""",
                (enrollment_id, enrollment["assessment_id"]),
            ).fetchone()
            if prior and not body.reissue:
                conn.commit()
                return {"id": prior["id"], "certificate_number": prior["certificate_number"], "issued_at": prior["issued_at"], "already_issued": True}
            storage = _certificate_dir(Path(app.state.db_path))
            template, raw = _template_bytes(conn, template["id"], storage)
            sequence = conn.execute(
                """SELECT COUNT(*) FROM certificate_issue ci
                   JOIN exam_enrollment ee ON ee.id=ci.enrollment_id
                   JOIN exam e ON e.id=ee.exam_id
                   WHERE e.year=? AND ee.scheme_kode=?""",
                (enrollment["exam_year"], enrollment["scheme_kode"]),
            ).fetchone()[0] + 1
            current_status = conn.execute("SELECT status FROM exam WHERE id=?", (enrollment["exam_id"],)).fetchone()
            if current_status is None or current_status["status"] == "archived":
                fail(409, "exam_archived")
            number = f"AA-{enrollment['exam_year']}-{enrollment['scheme_kode']}-{sequence:05d}"
            values = _certificate_values(enrollment, result, number)
            with tempfile.TemporaryDirectory(prefix="aeroassess-certificate-") as directory:
                work = Path(directory)
                _render_docx(raw, values, work / "source.docx")
                pdf = _convert_docx_to_pdf(work / "source.docx", work)
            key = f"certificate-{uuid.uuid4().hex}.pdf"
            path = storage / key
            now = db.utcnow()
            path.write_bytes(pdf)
            path.chmod(0o600)
            if prior:
                conn.execute("UPDATE certificate_issue SET status='superseded' WHERE id=?", (prior["id"],))
            cursor = conn.execute(
                """INSERT INTO certificate_issue
                   (enrollment_id, assessment_id, template_id, certificate_number, storage_key,
                    checksum, status, supersedes_id, issued_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
                (
                    enrollment_id,
                    enrollment["assessment_id"],
                    template["id"],
                    number,
                    key,
                    hashlib.sha256(pdf).hexdigest(),
                    prior["id"] if prior else None,
                    now,
                    now,
                ),
            )
            issue_id = cursor.lastrowid
            db.audit(
                conn,
                user["id"],
                "certificate_issue" if not prior else "certificate_reissue",
                "certificate_issue",
                issue_id,
                old_value={"superseded_id": prior["id"]} if prior else None,
                new_value={"enrollment_id": enrollment_id, "certificate_number": number, "template_id": template["id"]},
            )
            conn.commit()
        except Exception:
            conn.rollback()
            path.unlink(missing_ok=True)
            raise
        return {"id": issue_id, "certificate_number": number, "issued_at": now, "already_issued": False}

    @app.get("/api/certificates/{certificate_id}/download")
    def download_certificate(certificate_id: int, ctx: tuple = Depends(auth_ctx)):
        conn, user = ctx
        row = conn.execute("SELECT * FROM certificate_issue WHERE id=?", (certificate_id,)).fetchone()
        if row is None:
            fail(404, "certificate_not_found")
        storage = _certificate_dir(Path(app.state.db_path))
        path = (storage / row["storage_key"]).resolve()
        if path.parent != storage or not path.is_file():
            fail(404, "certificate_file_missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["checksum"]:
            fail(500, "certificate_integrity_failed")
        enrollment = conn.execute(
            "SELECT snapshot_name FROM exam_enrollment WHERE id=?", (row["enrollment_id"],)
        ).fetchone()
        db.audit(conn, user["id"], "certificate_download", "certificate_issue", certificate_id)
        conn.commit()
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=_safe_download_name(f"{enrollment['snapshot_name']}-{row['certificate_number']}"),
        )
