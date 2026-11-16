"""Koneksi SQLite, migrasi multi-skema, helper config, audit, dan snapshot.

Penjelasan Teknis (1-2 kalimat): Modul ini menggunakan SQLite dengan mode `WAL` (Write-Ahead Logging)
agar pembacaan dan penulisan dapat berjalan paralel tanpa saling mengunci, serta menyertakan migrasi
skema otomatis (`_migrate_multi_scheme`) sehingga database lama tetap kompatibel saat di-upgrade ke multi-skema.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "ukk.db"
DEFAULT_SCHEME_KODE = "JNT-SMK"


def utcnow() -> str:
    """Waktu ISO-8601 UTC, contoh ``2026-11-06T10:00:00Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_after(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_db_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    env = os.environ.get("DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_DB_PATH


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def open_db(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS scheme (
  kode TEXT PRIMARY KEY,
  nama TEXT NOT NULL,
  kategori TEXT NOT NULL DEFAULT 'Sertifikasi & Vokasi',
  deskripsi TEXT,
  pass_threshold INTEGER NOT NULL DEFAULT 70,
  technical_weight INTEGER NOT NULL DEFAULT 60,
  knowledge_weight INTEGER NOT NULL DEFAULT 40,
  final_pass_threshold INTEGER NOT NULL DEFAULT 65,
  min_sub_passed INTEGER NOT NULL DEFAULT 1,
  predicate_sangat_mahir INTEGER NOT NULL DEFAULT 90,
  predicate_mahir INTEGER NOT NULL DEFAULT 80,
  predicate_cakap INTEGER NOT NULL DEFAULT 70,
  templates_json TEXT,
  aktif INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS school (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kode TEXT NOT NULL UNIQUE,
  nama TEXT NOT NULL,
  scheme_kode TEXT NOT NULL DEFAULT 'JNT-SMK' REFERENCES scheme(kode),
  alamat TEXT,
  kontak TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_school_nama_norm ON school(lower(replace(nama, '  ', ' ')));

CREATE TABLE IF NOT EXISTS participant (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  school_id INTEGER NOT NULL REFERENCES school(id),
  nomor TEXT NOT NULL,
  nama TEXT NOT NULL,
  kelas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(school_id, nomor)
);

CREATE TABLE IF NOT EXISTS unit (
  kode TEXT PRIMARY KEY,
  scheme_kode TEXT NOT NULL DEFAULT 'JNT-SMK' REFERENCES scheme(kode) ON DELETE CASCADE,
  judul TEXT NOT NULL,
  urutan INTEGER NOT NULL,
  aktif INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(scheme_kode, urutan)
);

CREATE TABLE IF NOT EXISTS indicator (
  kode TEXT PRIMARY KEY,
  unit_kode TEXT NOT NULL REFERENCES unit(kode) ON DELETE CASCADE,
  teks TEXT NOT NULL,
  urutan INTEGER NOT NULL,
  aktif INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  is_proposed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(unit_kode, urutan)
);

CREATE TABLE IF NOT EXISTS sub_competency (
  kode TEXT PRIMARY KEY,
  scheme_kode TEXT NOT NULL DEFAULT 'JNT-SMK' REFERENCES scheme(kode) ON DELETE CASCADE,
  judul TEXT NOT NULL,
  urutan INTEGER NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(scheme_kode, urutan)
);

CREATE TABLE IF NOT EXISTS sub_competency_unit (
  sub_competency_kode TEXT NOT NULL REFERENCES sub_competency(kode) ON DELETE CASCADE,
  unit_kode TEXT NOT NULL REFERENCES unit(kode) ON DELETE CASCADE,
  PRIMARY KEY (sub_competency_kode, unit_kode)
);

CREATE TABLE IF NOT EXISTS assessment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  participant_id INTEGER NOT NULL REFERENCES participant(id),
  scheme_kode TEXT NOT NULL DEFAULT 'JNT-SMK',
  instrument_version INTEGER NOT NULL,
  instrument_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'in_progress',
  started_at TEXT NOT NULL,
  locked_at TEXT,
  locked_by INTEGER,
  unlocked_at TEXT,
  unlocked_by INTEGER,
  unlock_reason TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS score (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL REFERENCES assessment(id) ON DELETE CASCADE,
  indicator_kode TEXT NOT NULL REFERENCES indicator(kode),
  value INTEGER,
  note TEXT,
  synced INTEGER NOT NULL DEFAULT 1,
  client_ts TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(assessment_id, indicator_kode)
);

CREATE TABLE IF NOT EXISTS config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  payload_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending',
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  processed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  user_id INTEGER NOT NULL DEFAULT 1,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  metadata TEXT
);

CREATE TABLE IF NOT EXISTS user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  totp_secret TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen TEXT
);

CREATE TABLE IF NOT EXISTS exam (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  year INTEGER,
  starts_on TEXT,
  ends_on TEXT,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'active', 'closed', 'archived')),
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_exam_title_year
  ON exam(lower(trim(title)), year) WHERE year IS NOT NULL;

CREATE TABLE IF NOT EXISTS exam_school (
  exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE RESTRICT,
  school_id INTEGER NOT NULL REFERENCES school(id) ON DELETE RESTRICT,
  PRIMARY KEY (exam_id, school_id)
);

CREATE TABLE IF NOT EXISTS exam_scheme (
  exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE RESTRICT,
  scheme_kode TEXT NOT NULL REFERENCES scheme(kode) ON DELETE RESTRICT,
  PRIMARY KEY (exam_id, scheme_kode)
);

CREATE TABLE IF NOT EXISTS exam_enrollment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE RESTRICT,
  participant_id INTEGER NOT NULL REFERENCES participant(id) ON DELETE RESTRICT,
  school_id INTEGER NOT NULL REFERENCES school(id) ON DELETE RESTRICT,
  scheme_kode TEXT NOT NULL REFERENCES scheme(kode) ON DELETE RESTRICT,
  group_label TEXT NOT NULL DEFAULT '',
  snapshot_number TEXT NOT NULL,
  snapshot_name TEXT NOT NULL,
  snapshot_class TEXT NOT NULL DEFAULT '',
  snapshot_school_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enrolled' CHECK (status IN ('enrolled', 'withdrawn')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (exam_id, participant_id, scheme_kode)
);

CREATE TABLE IF NOT EXISTS certificate_template (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exam_id INTEGER REFERENCES exam(id) ON DELETE RESTRICT,
  scheme_kode TEXT REFERENCES scheme(kode) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  original_name TEXT NOT NULL,
  storage_key TEXT NOT NULL UNIQUE,
  checksum TEXT NOT NULL,
  placeholders_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0,
  previewed_at TEXT,
  uploaded_by INTEGER NOT NULL REFERENCES user(id),
  created_at TEXT NOT NULL,
  CHECK (exam_id IS NOT NULL OR scheme_kode IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS certificate_issue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  enrollment_id INTEGER NOT NULL REFERENCES exam_enrollment(id) ON DELETE RESTRICT,
  assessment_id INTEGER NOT NULL REFERENCES assessment(id) ON DELETE RESTRICT,
  template_id INTEGER NOT NULL REFERENCES certificate_template(id) ON DELETE RESTRICT,
  certificate_number TEXT NOT NULL UNIQUE,
  storage_key TEXT NOT NULL UNIQUE,
  checksum TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
  supersedes_id INTEGER REFERENCES certificate_issue(id) ON DELETE RESTRICT,
  issued_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_score_assessment ON score(assessment_id);
CREATE INDEX IF NOT EXISTS idx_score_pending ON score(synced) WHERE synced=0;
CREATE INDEX IF NOT EXISTS idx_assessment_participant ON assessment(participant_id);
CREATE INDEX IF NOT EXISTS idx_participant_school ON participant(school_id);
CREATE INDEX IF NOT EXISTS idx_sync_outbox_status ON sync_outbox(status);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);
CREATE INDEX IF NOT EXISTS idx_exam_status_year ON exam(status, year DESC);
CREATE INDEX IF NOT EXISTS idx_exam_enrollment_exam ON exam_enrollment(exam_id, status, id);
CREATE INDEX IF NOT EXISTS idx_exam_enrollment_school ON exam_enrollment(school_id, exam_id);
CREATE INDEX IF NOT EXISTS idx_certificate_issue_enrollment
  ON certificate_issue(enrollment_id, assessment_id, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_certificate_issue_active
  ON certificate_issue(enrollment_id, assessment_id) WHERE status = 'active';
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_multi_scheme(conn: sqlite3.Connection) -> None:
    """Migrasi aman untuk database eksisting yang belum memiliki kolom/tabel multi-skema."""
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA legacy_alter_table=ON")
    try:
        for tbl in ("school", "assessment"):
            cols = _table_columns(conn, tbl)
            if cols and "scheme_kode" not in cols:
                conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN scheme_kode TEXT NOT NULL DEFAULT '{DEFAULT_SCHEME_KODE}'"
                )

        unit_cols = _table_columns(conn, "unit")
        if unit_cols and "scheme_kode" not in unit_cols:
            conn.executescript(
                """
                CREATE TABLE unit_new (
                  kode TEXT PRIMARY KEY,
                  scheme_kode TEXT NOT NULL DEFAULT 'JNT-SMK' REFERENCES scheme(kode) ON DELETE CASCADE,
                  judul TEXT NOT NULL,
                  urutan INTEGER NOT NULL,
                  aktif INTEGER NOT NULL DEFAULT 1,
                  version INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(scheme_kode, urutan)
                );
                INSERT INTO unit_new (kode, scheme_kode, judul, urutan, aktif, version, created_at, updated_at)
                SELECT kode, 'JNT-SMK', judul, urutan, aktif, version, created_at, updated_at FROM unit;
                DROP TABLE unit;
                ALTER TABLE unit_new RENAME TO unit;
                """
            )

        sub_cols = _table_columns(conn, "sub_competency")
        if sub_cols and "scheme_kode" not in sub_cols:
            conn.executescript(
                """
                CREATE TABLE sub_competency_new (
                  kode TEXT PRIMARY KEY,
                  scheme_kode TEXT NOT NULL DEFAULT 'JNT-SMK' REFERENCES scheme(kode) ON DELETE CASCADE,
                  judul TEXT NOT NULL,
                  urutan INTEGER NOT NULL,
                  version INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(scheme_kode, urutan)
                );
                INSERT INTO sub_competency_new (kode, scheme_kode, judul, urutan, version, created_at, updated_at)
                SELECT kode, 'JNT-SMK', judul, urutan, version, created_at, updated_at FROM sub_competency;
                DROP TABLE sub_competency;
                ALTER TABLE sub_competency_new RENAME TO sub_competency;
                """
            )

        # Perbaiki referensi FK bila sempat tercatat ke unit_old / sub_competency_old atau sub_kode
        bad_fk = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND (sql LIKE '%unit_old%' OR sql LIKE '%sub_competency_old%' OR sql LIKE '%sub_kode%')"
        ).fetchall()
        if bad_fk:
            scu_cols = _table_columns(conn, "sub_competency_unit")
            src_col = "sub_kode" if "sub_kode" in scu_cols else "sub_competency_kode"
            conn.executescript(
                f"""
                CREATE TABLE indicator_new (
                  kode TEXT PRIMARY KEY,
                  unit_kode TEXT NOT NULL REFERENCES unit(kode) ON DELETE CASCADE,
                  teks TEXT NOT NULL,
                  urutan INTEGER NOT NULL,
                  aktif INTEGER NOT NULL DEFAULT 1,
                  is_proposed INTEGER NOT NULL DEFAULT 0,
                  version INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(unit_kode, urutan)
                );
                INSERT INTO indicator_new SELECT * FROM indicator;
                DROP TABLE indicator;
                ALTER TABLE indicator_new RENAME TO indicator;

                CREATE TABLE sub_competency_unit_new (
                  sub_competency_kode TEXT NOT NULL REFERENCES sub_competency(kode) ON DELETE CASCADE,
                  unit_kode TEXT NOT NULL REFERENCES unit(kode) ON DELETE RESTRICT,
                  PRIMARY KEY (sub_competency_kode, unit_kode)
                );
                INSERT INTO sub_competency_unit_new (sub_competency_kode, unit_kode)
                SELECT {src_col}, unit_kode FROM sub_competency_unit;
                DROP TABLE sub_competency_unit;
                ALTER TABLE sub_competency_unit_new RENAME TO sub_competency_unit;
                """
            )
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table=OFF")
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_annual_exams(conn: sqlite3.Connection) -> None:
    """Add exam context without assigning historical assessments to invented exams."""
    columns = _table_columns(conn, "assessment")
    if "exam_enrollment_id" not in columns:
        conn.execute(
            "ALTER TABLE assessment ADD COLUMN exam_enrollment_id INTEGER "
            "REFERENCES exam_enrollment(id) ON DELETE RESTRICT"
        )
    template_columns = _table_columns(conn, "certificate_template")
    if "previewed_at" not in template_columns:
        conn.execute("ALTER TABLE certificate_template ADD COLUMN previewed_at TEXT")
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_enrollment
          ON assessment(exam_enrollment_id) WHERE exam_enrollment_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_certificate_template_scope
          ON certificate_template(exam_id, scheme_kode, active, version DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_certificate_issue_active
          ON certificate_issue(enrollment_id, assessment_id) WHERE status = 'active';
        """
    )
    conn.commit()


def _migrate_scheme_weights(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(scheme)").fetchall()}
    migrations = [
        ("technical_weight", "INTEGER NOT NULL DEFAULT 60"),
        ("knowledge_weight", "INTEGER NOT NULL DEFAULT 40"),
        ("final_pass_threshold", "INTEGER NOT NULL DEFAULT 65"),
        ("min_sub_passed", "INTEGER NOT NULL DEFAULT 1"),
    ]
    for col_name, col_def in migrations:
        if col_name not in cols:
            conn.execute(f"ALTER TABLE scheme ADD COLUMN {col_name} {col_def}")
    conn.commit()


def init_db(path: str | os.PathLike[str] | None = None) -> Path:
    try:
        from .seed_data import seed
    except ImportError:  # pragma: no cover
        from seed_data import seed

    db_path = resolve_db_path(path)
    with open_db(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate_multi_scheme(conn)
        _migrate_annual_exams(conn)
        _migrate_scheme_weights(conn)
        seed(conn)
    return db_path


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def get_config(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return row["value"]


def set_config(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        """
        INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, json.dumps(value), utcnow()),
    )


def all_config(conn: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value FROM config"):
        try:
            result[row["key"]] = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            result[row["key"]] = row["value"]
    return result


def instrument_version(conn: sqlite3.Connection, scheme_kode: str | None = None) -> int:
    if scheme_kode and scheme_kode != DEFAULT_SCHEME_KODE:
        row = conn.execute("SELECT version FROM scheme WHERE kode = ?", (scheme_kode,)).fetchone()
        if row is not None:
            return int(row["version"])
    try:
        return int(get_config(conn, "instrument_version", 1))
    except (TypeError, ValueError):
        return 1


def bump_instrument_version(conn: sqlite3.Connection, scheme_kode: str | None = None) -> int:
    version = instrument_version(conn) + 1
    now = utcnow()
    set_config(conn, "instrument_version", version)
    set_config(conn, "instrument_updated_at", now)
    target_scheme = scheme_kode or DEFAULT_SCHEME_KODE
    conn.execute(
        "UPDATE scheme SET version = ?, updated_at = ? WHERE kode = ?",
        (version, now, target_scheme),
    )
    return version


def audit(
    conn: sqlite3.Connection,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    old_value: Any = None,
    new_value: Any = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log
            (timestamp, user_id, action, entity_type, entity_id, old_value, new_value, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utcnow(),
            user_id or 1,
            action,
            entity_type,
            str(entity_id),
            json.dumps(old_value, default=str) if old_value is not None else None,
            json.dumps(new_value, default=str) if new_value is not None else None,
            json.dumps(metadata, default=str) if metadata is not None else None,
        ),
    )


def record_outbox(
    conn: sqlite3.Connection,
    payload_type: str,
    idempotency_key: str,
    payload: Any,
    status: str = "done",
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sync_outbox
            (payload_type, payload_json, idempotency_key, status, retry_count, last_error, created_at, processed_at)
        VALUES (?, ?, ?, ?, 0, ?, ?, ?)
        ON CONFLICT(idempotency_key) DO UPDATE SET
            payload_json = excluded.payload_json,
            status = excluded.status,
            last_error = excluded.last_error,
            processed_at = excluded.processed_at
        """,
        (
            payload_type,
            json.dumps(payload, ensure_ascii=False),
            idempotency_key,
            status,
            error,
            utcnow(),
            utcnow() if status == "done" else None,
        ),
    )


def get_snapshot(conn: sqlite3.Connection, scheme_kode: str = DEFAULT_SCHEME_KODE) -> dict[str, Any]:
    """Snapshot instrumen aktif untuk assessment baru pada skema tertentu."""
    scheme_row = conn.execute(
        "SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)
    ).fetchone()
    if scheme_row is None:
        scheme_kode = DEFAULT_SCHEME_KODE
        scheme_row = conn.execute(
            "SELECT * FROM scheme WHERE kode = ?", (scheme_kode,)
        ).fetchone()

    units: list[dict[str, Any]] = []
    for unit in conn.execute(
        "SELECT kode, judul, urutan, version FROM unit WHERE scheme_kode = ? AND aktif = 1 ORDER BY urutan",
        (scheme_kode,),
    ):
        indicators = [
            dict(ind)
            for ind in conn.execute(
                """
                SELECT kode, teks, urutan, is_proposed
                FROM indicator WHERE unit_kode = ? AND aktif = 1 ORDER BY urutan
                """,
                (unit["kode"],),
            )
        ]
        if not indicators:
            continue
        units.append(
            {
                "kode": unit["kode"],
                "judul": unit["judul"],
                "urutan": unit["urutan"],
                "version": unit["version"],
                "indicators": indicators,
            }
        )

    unit_codes = {u["kode"] for u in units}
    subs: list[dict[str, Any]] = []
    for sub in conn.execute(
        "SELECT kode, judul, urutan FROM sub_competency WHERE scheme_kode = ? ORDER BY urutan",
        (scheme_kode,),
    ):
        links = [
            r["unit_kode"]
            for r in conn.execute(
                "SELECT unit_kode FROM sub_competency_unit WHERE sub_competency_kode = ?",
                (sub["kode"],),
            )
            if r["unit_kode"] in unit_codes
        ]
        subs.append(
            {
                "kode": sub["kode"],
                "judul": sub["judul"],
                "urutan": sub["urutan"],
                "unit_kodes": links,
            }
        )

    templates = parse_json(scheme_row["templates_json"] if scheme_row else None)
    return {
        "scheme_kode": scheme_kode,
        "scheme_nama": scheme_row["nama"] if scheme_row else "Junior Network Technician",
        "version": instrument_version(conn, scheme_kode),
        "units": units,
        "sub_competencies": subs,
        "thresholds": {
            "pass_threshold": scheme_row["pass_threshold"] if scheme_row else 70,
            "technical_weight": scheme_row["technical_weight"] if scheme_row and "technical_weight" in scheme_row.keys() else 60,
            "knowledge_weight": scheme_row["knowledge_weight"] if scheme_row and "knowledge_weight" in scheme_row.keys() else 40,
            "final_pass_threshold": scheme_row["final_pass_threshold"] if scheme_row and "final_pass_threshold" in scheme_row.keys() else 65,
            "min_sub_passed": scheme_row["min_sub_passed"] if scheme_row and "min_sub_passed" in scheme_row.keys() else 1,
            "predicate_sangat_mahir": scheme_row["predicate_sangat_mahir"] if scheme_row else 90,
            "predicate_mahir": scheme_row["predicate_mahir"] if scheme_row else 80,
            "predicate_cakap": scheme_row["predicate_cakap"] if scheme_row else 70,
        },
        "templates": templates,
    }


def parse_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
