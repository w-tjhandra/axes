"""Backup SQLite memakai backup API, permission 0600, enkripsi opsional, dan retensi 30 hari.

Penjelasan Teknis (1-2 kalimat): Modul ini menggunakan API `sqlite3.Connection.backup()` bawaan
untuk menyalin halaman database secara atomik saat server sedang aktif (online hot-backup), lalu
mengunci permission file ke `0600` (`rw-------`) agar tidak dapat dibaca oleh user lain di server Linux.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from .db import resolve_db_path, utcnow
except ImportError:  # pragma: no cover
    from db import resolve_db_path, utcnow  # type: ignore[no-redef]

DEFAULT_RETENTION_DAYS = 30


def backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", "./backups")).expanduser().resolve()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _encrypt_backup_file(target: Path, out_dir: Path, key: str) -> Path:
    """Enkripsi file backup SQLite dengan AES-256-CBC PBKDF2 melalui OpenSSL."""
    if shutil.which("openssl") is None:
        target.unlink(missing_ok=True)
        raise RuntimeError("BACKUP_KEY diset tetapi openssl tidak tersedia")
    enc = out_dir / f"{target.name}.enc"
    env = os.environ.copy()
    env["BACKUP_KEY"] = key
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-pass",
            "env:BACKUP_KEY",
            "-in",
            str(target),
            "-out",
            str(enc),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        enc.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise RuntimeError(f"openssl gagal: {proc.stderr.strip()[:300]}")
    target.unlink(missing_ok=True)
    return enc


def create_backup(
    db_path: str | os.PathLike[str] | None = None,
    target_dir: str | os.PathLike[str] | None = None,
    backup_key: str | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    src_path = resolve_db_path(db_path)
    out_dir = Path(target_dir).expanduser().resolve() if target_dir else backup_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = _timestamp()
    filename = f"ukk_{stamp}.sqlite3"
    target = out_dir / filename

    src = sqlite3.connect(src_path, timeout=10.0)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    encrypted = False
    key = backup_key if backup_key is not None else os.environ.get("BACKUP_KEY")
    if key:
        target = _encrypt_backup_file(target, out_dir, key)
        filename = target.name
        encrypted = True

    try:
        os.chmod(target, 0o600)
    except OSError:
        pass

    documents_dir = Path(
        os.environ.get("CERTIFICATE_DIR", str(src_path.parent / "certificates"))
    ).expanduser().resolve()
    documents_filename = None
    documents_size = 0
    documents = sorted(
        path for path in documents_dir.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name.startswith(("template-", "certificate-"))
    ) if documents_dir.is_dir() else []
    if documents:
        documents_target = out_dir / f"ukk_{stamp}.documents.zip"
        with zipfile.ZipFile(documents_target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in documents:
                if path.resolve().parent != documents_dir:
                    continue
                archive.write(path, arcname=path.name)
        try:
            os.chmod(documents_target, 0o600)
        except OSError:
            pass
        if key:
            documents_target = _encrypt_backup_file(documents_target, out_dir, key)
        documents_filename = documents_target.name
        documents_size = documents_target.stat().st_size

    purge_old_backups(out_dir, retention_days)
    stat = target.stat()
    return {
        "filename": filename,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "encrypted": encrypted,
        "retention_days": retention_days,
        "documents_filename": documents_filename,
        "documents_size_bytes": documents_size,
    }


def purge_old_backups(out_dir: Path, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for item in out_dir.glob("ukk_*"):
        if ".sqlite3" not in item.name and ".documents.zip" not in item.name:
            continue
        if not item.is_file():
            continue
        mtime = datetime.fromtimestamp(item.stat().st_mtime, timezone.utc)
        if mtime < cutoff:
            item.unlink(missing_ok=True)
            removed += 1
    return removed


def list_backups(target_dir: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    out_dir = Path(target_dir).expanduser().resolve() if target_dir else backup_dir()
    if not out_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    candidates = [
        item
        for item in out_dir.glob("ukk_*")
        if item.is_file() and (".sqlite3" in item.name or ".documents.zip" in item.name)
    ]
    for item in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        if not item.is_file():
            continue
        stat = item.stat()
        items.append(
            {
                "filename": item.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "encrypted": item.name.endswith(".enc"),
                "backup_type": "documents" if ".documents.zip" in item.name else "database",
            }
        )
    return items


def main() -> None:  # pragma: no cover - dipakai oleh backup.sh
    info = create_backup()
    print(f"Backup dibuat: {info['filename']} ({info['size_bytes']} byte)")


if __name__ == "__main__":  # pragma: no cover
    main()
