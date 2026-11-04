"""
Вход в веб-приложение без паролей:
1. В боте жмёшь «🌐 Приложение» → бот даёт одноразовый код (живёт 10 минут).
2. Вводишь код на сайте (или открываешь ссылку) → сайт получает сессионный токен.
В базе лежат только SHA-256 хэши кодов и токенов: даже утёкшая база не даст войти.
"""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

CODE_TTL = timedelta(minutes=10)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # без 0/O и 1/I, чтобы не путать
MAX_FAILED_ATTEMPTS = 5


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Auth:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.failed = 0

    def new_code(self) -> str:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        self.conn.execute("DELETE FROM login_codes WHERE expires_at < ?", (_now().isoformat(),))
        self.conn.execute("INSERT INTO login_codes (code_hash, expires_at) VALUES (?, ?)",
                          (_h(code), (_now() + CODE_TTL).isoformat()))
        self.conn.commit()
        self.failed = 0
        return code

    def exchange(self, code: str, device: str = "") -> str | None:
        """Меняет код на токен сессии. None — код неверный или протух."""
        code = code.strip().upper().replace("-", "").replace(" ", "")
        row = self.conn.execute("SELECT expires_at FROM login_codes WHERE code_hash = ?",
                                (_h(code),)).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) < _now():
            self.failed += 1
            if self.failed >= MAX_FAILED_ATTEMPTS:
                # перебор? сжигаем все активные коды — придётся запросить новый в боте
                self.conn.execute("DELETE FROM login_codes")
                self.conn.commit()
            return None
        self.conn.execute("DELETE FROM login_codes WHERE code_hash = ?", (_h(code),))
        token = secrets.token_urlsafe(32)
        self.conn.execute("INSERT INTO sessions (token_hash, device) VALUES (?, ?)",
                          (_h(token), device[:120]))
        self.conn.commit()
        self.failed = 0
        return token

    def check(self, token: str) -> bool:
        if not token:
            return False
        cur = self.conn.execute("UPDATE sessions SET last_seen = datetime('now') WHERE token_hash = ?",
                                (_h(token),))
        self.conn.commit()
        return cur.rowcount == 1

    def logout(self, token: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_h(token),))
        self.conn.commit()

    def logout_all(self) -> int:
        cur = self.conn.execute("DELETE FROM sessions")
        self.conn.commit()
        return cur.rowcount

    def sessions_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
