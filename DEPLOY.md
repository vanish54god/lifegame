# 🚀 Деплой на VPS

Когда будет сервер, это займёт минут 20. Всё крутится в Docker: бот, приложение и Caddy (он сам делает HTTPS).

## Что понадобится

1. **VPS** с Ubuntu 22.04/24.04, хватит 1 ядра и 1 ГБ RAM.
2. **Домен** (HTTPS обязателен, иначе iPhone/iPad не установят приложение как PWA). Варианты:
   - купить свой (`.ru` — пара сотен рублей в год) и сделать A-запись на IP сервера;
   - бесплатный поддомен, например на duckdns.org (тоже A-запись на IP сервера).
3. Проверь, что с сервера доступен Telegram: `curl -sI https://api.telegram.org | head -1` должен ответить `HTTP/...`.

## Шаги

```bash
# 1. Подключаемся
ssh root@IP_СЕРВЕРА

# 2. Ставим Docker
curl -fsSL https://get.docker.com | sh

# 3. Закрываем всё лишнее файрволом
apt install -y ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable

# 4. Заливаем проект (с ноута, из папки на уровень выше lifegame):
#    scp -r lifegame root@IP_СЕРВЕРА:/opt/
#    или через git clone, если залил на GitHub (без .env и game.db!)
cd /opt/lifegame

# 5. Настройки
cp .env.example .env
nano .env
#   BOT_TOKEN=...            тот же токен
#   OWNER_ID=...             твой ID
#   DOMAIN=game.твой-домен.ru
#   PUBLIC_URL=https://game.твой-домен.ru

# 6. Перенос прогресса с ноута (если уже играл):
#    scp game.db root@IP_СЕРВЕРА:/opt/lifegame/data/game.db
mkdir -p data && chown 1000:1000 data

# 7. Запуск
docker compose up -d --build
docker compose logs -f app     # выход: Ctrl+C (бот продолжит работать)
```

⚠️ **Важно:** один токен = один запущенный бот. Перед запуском на сервере останови бота на ноуте, иначе Telegram будет ругаться (ошибка `Conflict`).

## Обновление

```bash
cd /opt/lifegame
# залей новые файлы (scp или git pull), потом:
docker compose up -d --build
```

## Бэкапы

Весь прогресс — один файл `data/game.db`. Ежедневный бэкап через cron:

```bash
mkdir -p /opt/lifegame/backups
crontab -e
# добавь строку (каждый день в 4:00, хранит 30 последних копий):
0 4 * * * cd /opt/lifegame && sqlite3 data/game.db ".backup backups/game-$(date +\%F).db" && ls -t backups/*.db | tail -n +31 | xargs -r rm
```

(`apt install -y sqlite3`, если команды нет.) Скачать бэкап на ноут: `scp root@IP:/opt/lifegame/backups/game-ДАТА.db .`

## Безопасность (для инфобезника 😄)

- Приложение наружу не торчит: порт 8000 открыт только внутри Docker-сети, снаружи — только Caddy на 80/443.
- HTTPS + HSTS, заголовки CSP / X-Frame-Options / nosniff, в API — `Cache-Control: no-store`.
- Вход: одноразовый код из бота (8 символов, 10 минут). После 5 неверных попыток все коды сгорают; не чаще 1 попытки в секунду.
- В базе только SHA-256 хэши кодов и сессий.
- Бот отвечает только твоему `OWNER_ID`.
- Контейнер работает не от root.
- Потерял телефон → `/logout_all` в боте.
- Для SSH лучше ключи вместо пароля: `ssh-copy-id root@IP`, затем `PasswordAuthentication no` в `/etc/ssh/sshd_config`.
