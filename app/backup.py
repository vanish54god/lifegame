"""
Бэкапы базы.
- Снимок делается штатным механизмом SQLite (база не ломается, даже если в этот момент идёт запись).
- Архив шифруется AES-256 паролем из .env (BACKUP_PASSWORD) — без пароля его не открыть.
- Локально хранятся последние 14 копий (папка backups рядом с базой), а ещё бот присылает архив тебе в Telegram.

Восстановить: распаковать архив (7-Zip / «Архиватор» на iPhone, пароль из .env) и положить game.db на место.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pyzipper

KEEP = 14


def make_backup(conn: sqlite3.Connection, db_path: str, password: str, now: datetime) -> Path:
    if not password:
        raise ValueError("Не задан BACKUP_PASSWORD в .env")
    folder = Path(db_path).resolve().parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d_%H%M")
    snap = folder / f"game-{stamp}.db"
    dst = sqlite3.connect(snap)
    try:
        conn.backup(dst)                     # консистентный снимок «на ходу»
    finally:
        dst.close()
    archive = folder / f"lifegame-{stamp}.zip"
    with pyzipper.AESZipFile(archive, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as z:
        z.setpassword(password.encode())
        z.write(snap, "game.db")
    snap.unlink()
    for old in sorted(folder.glob("lifegame-*.zip"))[:-KEEP]:
        old.unlink()
    return archive
