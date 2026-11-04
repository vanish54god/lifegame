"""Настройки читаются из файла .env (его нельзя заливать на GitHub!)."""

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass
class Config:
    bot_token: str
    owner_id: int          # твой Telegram ID; 0 = ещё не настроен
    db_path: str
    day_start_hour: int    # во сколько начинается новый игровой день
    tz: ZoneInfo
    public_url: str = "http://localhost:8000"   # адрес веб-приложения (на VPS — https://твой-домен)
    host: str = "0.0.0.0"
    port: int = 8000


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Нет BOT_TOKEN в файле .env — см. README")
    return Config(
        bot_token=token,
        owner_id=int(os.getenv("OWNER_ID", "0") or 0),
        db_path=os.getenv("DB_PATH", "game.db"),
        day_start_hour=int(os.getenv("DAY_START_HOUR", "5")),
        tz=ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
        public_url=os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
