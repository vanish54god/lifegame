"""
Точка входа: python main.py
Запускает в одном процессе: Telegram-бота, веб-приложение и напоминания.
"""

import asyncio

import uvicorn

from app.auth import Auth
from app.bot import COMMANDS, make_bot, reminders_loop
from app.config import load_config
from app.db import connect
from app.game import Game
from app.web import create_app


async def main() -> None:
    cfg = load_config()
    conn = connect(cfg.db_path)
    game, auth = Game(conn), Auth(conn)

    bot, dp = make_bot(cfg, game, auth)
    await bot.set_my_commands(COMMANDS)

    server = uvicorn.Server(uvicorn.Config(
        create_app(cfg, game, auth), host=cfg.host, port=cfg.port,
        log_level="warning", proxy_headers=True,
    ))

    print(f"🎮 Бот запущен. Веб-приложение: {cfg.public_url}  (остановить: Ctrl+C)")
    jobs = [dp.start_polling(bot, handle_signals=False), server.serve()]
    if cfg.owner_id:
        jobs.append(reminders_loop(bot, cfg, game))
    tasks = [asyncio.create_task(j) for j in jobs]
    # Когда что-то одно завершилось (например, Ctrl+C остановил веб-сервер) — гасим остальное
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Остановлено")
