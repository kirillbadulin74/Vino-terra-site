# Развёртывание vino-terra.ru на VPS

Пошаговая инструкция «арендовал сервер → сайт работает». Рассчитана на
Ubuntu 22.04/24.04 LTS, сервер в Европе (прямой доступ к api.openai.com,
VPN не нужен). Минимальная конфигурация: 1 vCPU, 1–2 ГБ RAM, 10 ГБ диска.

Схема:

```
Интернет
  └── nginx :80/:443 (vino-terra.ru, сертификат Let's Encrypt)
        ├── /            → статика  /opt/vinoterra/frontend
        └── /api/*       → proxy    127.0.0.1:8080 (uvicorn, FastAPI)
systemd:
  ├── vinoterra-api.service  — веб-API Нейро-сомелье
  └── vinoterra-bot.service  — Telegram-бот (long polling)
Общие данные: backend/knowledge_base, backend/vector_index,
              backend/feedback/feedback.db (лог вопросов бота и сайта)
```

## 0. DNS

У регистратора домена vino-terra.ru создать A-записи на IP сервера:

```
vino-terra.ru      A  <IP сервера>
www.vino-terra.ru  A  <IP сервера>
```

DNS может обновляться до пары часов; проверка: `ping vino-terra.ru`.

## 1. Первичная настройка сервера

Зайти по SSH (реквизиты даст хостер) и выполнить:

```bash
apt update && apt upgrade -y
apt install -y nginx python3 python3-venv git certbot python3-certbot-nginx

# отдельный пользователь для приложения (без sudo)
adduser --system --group --home /opt/vinoterra vinoterra

# файрвол: только SSH и веб
ufw allow OpenSSH && ufw allow "Nginx Full" && ufw enable
```

## 2. Код на сервер

```bash
cd /opt/vinoterra
git clone <URL репозитория vino-terra-site> app
# статика и бэкенд, как их ждут конфиги:
ln -s /opt/vinoterra/app/frontend /opt/vinoterra/frontend
ln -s /opt/vinoterra/app/backend  /opt/vinoterra/backend
```

(Либо без git: залить папку архивом `scp vino-terra-site.zip root@IP:/opt/vinoterra/`
и распаковать. Обновления тогда тоже руками.)

## 3. Python-окружение

```bash
cd /opt/vinoterra/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 4. Ключи и настройки (.env)

```bash
cp .env.example .env
nano .env
```

Заполнить обязательно:

- `OPENAI_API_KEY` — ключ OpenAI (сервер в Европе → работает напрямую);
- `TELEGRAM_BOT_TOKEN` — токен бота от @BotFather;
- `TRUST_PROXY_HEADERS=1` — мы за nginx, rate-limit должен видеть реальные IP;
- `ENABLE_API_DOCS=0` — Swagger в проде выключен.

Опционально: `FALLBACK_API_KEY` (vedai.by) — включает фоллбэк DeepSeek при
сбоях OpenAI. `ALLOWED_ORIGINS` уже содержит vino-terra.ru в дефолте web_api,
но в .env лучше указать явно.

Права: `chown -R vinoterra:vinoterra /opt/vinoterra/app && chmod 600 .env`.

## 5. Векторный индекс

Готовый кеш `vector_index/` (2824 чанка) уже в репозитории — пересчёт не нужен,
API поднимется сразу. Пересборка нужна только после правок базы знаний:

```bash
cd /opt/vinoterra/backend && sudo -u vinoterra .venv/bin/python build_vector_index.py
```

## 6. Сервисы systemd

```bash
cp /opt/vinoterra/app/deploy/vinoterra-api.service /etc/systemd/system/
cp /opt/vinoterra/app/deploy/vinoterra-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vinoterra-api vinoterra-bot

# проверка
systemctl status vinoterra-api vinoterra-bot
curl http://127.0.0.1:8080/api/health   # {"status":"ok","chunks":2824,...}
```

Логи: `journalctl -u vinoterra-api -f` (и `-u vinoterra-bot`).

## 7. nginx и HTTPS

```bash
cp /opt/vinoterra/app/deploy/nginx-vino-terra.conf /etc/nginx/sites-available/vino-terra.ru
ln -s /etc/nginx/sites-available/vino-terra.ru /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# сертификат (когда DNS уже указывает на сервер):
certbot --nginx -d vino-terra.ru -d www.vino-terra.ru
```

certbot сам перепишет конфиг на HTTPS с редиректом и настроит автопродление.

## 8. Финальная проверка

- https://vino-terra.ru — сайт открывается, стили и картинки на месте;
- кнопка «Нейро-сомелье» → чат → вопрос «Что такое танины в вине?» → ответ;
- 👍/👎 под ответом нажимаются («Спасибо за оценку!»);
- Telegram: бот отвечает (@VinoTerra_AI_bot);
- `sqlite3 /opt/vinoterra/backend/feedback/feedback.db "SELECT channel, COUNT(*) FROM interactions GROUP BY channel;"`
  — видны и web, и telegram.

## Обновление сайта/бэкенда

```bash
cd /opt/vinoterra/app && git pull
# если менялись данные сайта: они статические, хватает git pull
# если менялась база знаний: пересобрать индекс (см. шаг 5)
systemctl restart vinoterra-api vinoterra-bot   # только если менялся backend
```

## Частые проблемы

| Симптом | Причина / решение |
|---|---|
| `502` от /api | uvicorn не поднялся — `journalctl -u vinoterra-api -n 50` |
| Чат: «Слишком много запросов» | rate-limit (10/мин с IP) — это штатно |
| Ответы медленные (30–60 с) | норма для RAG с gpt-4o-mini; nginx-таймаут уже 120 с |
| OpenAI 403 (гео) | сервер не в поддерживаемом регионе — сменить локацию VPS; временно спасает FALLBACK_API_KEY |
| Бот молчит | `journalctl -u vinoterra-bot`; проверить TELEGRAM_BOT_TOKEN; бот должен быть запущен только в одном месте (long polling не терпит два процесса) |
