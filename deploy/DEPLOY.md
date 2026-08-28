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

Про `TRUST_PROXY_HEADERS` — это не косметика, на живом сервере переменную
забыли, и лимит работал неправильно почти месяц. При `0` бэкенд считает
клиентом сам nginx, то есть `127.0.0.1`, и `RATE_LIMIT_REQUESTS=10` становится
одним ведром на весь интернет: одиннадцатый вопрос за минуту от любого
посетителя получает 429, хотя человек спросил впервые. Со стороны это выглядит
как «чат иногда не отвечает». Проверить, что значение действительно доехало
(в unit-файле `EnvironmentFile` нет, `.env` читает сам `run_web_api.py`, поэтому
в `/proc/<pid>/environ` переменной не видно):

```bash
cd /opt/vinoterra/backend && .venv/bin/python -c \
  "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('TRUST_PROXY_HEADERS'))"
```

Включать `TRUST_PROXY_HEADERS=1` можно только вместе с
`proxy_set_header X-Forwarded-For $remote_addr;` из `deploy/nginx-vino-terra.conf`.
Если в nginx оставить `$proxy_add_x_forwarded_for`, заголовок дописывается к
присланному клиентом, бэкенд берёт из него первый адрес — и посетитель, меняя
`X-Forwarded-For` каждые десять запросов, тратит платный ключ без ограничений.
Две половины настройки имеют смысл только вместе.

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
| Чат: «Слишком много запросов» | rate-limit (10/мин с IP) — это штатно. Но если 429 ловят разные люди с первого вопроса, проверьте `TRUST_PROXY_HEADERS` (см. шаг 4): при `0` лимит общий на всех |
| Ответы медленные (30–60 с) | норма для RAG с gpt-4o-mini; nginx-таймаут уже 120 с |
| OpenAI 403 (гео) | сервер не в поддерживаемом регионе — сменить локацию VPS; временно спасает FALLBACK_API_KEY |
| Бот молчит | `journalctl -u vinoterra-bot`; проверить TELEGRAM_BOT_TOKEN; бот должен быть запущен только в одном месте (long polling не терпит два процесса) |

## Как сейчас развёрнуто на реальном сервере (28.08.2026)

Живая установка отличается от инструкции выше — она делалась раньше и вручную,
файлы копировались по scp, git на сервере нет. Записано, чтобы следующая правка
конфига не сломала работающий сайт:

| | Инструкция выше | Фактически на сервере |
|---|---|---|
| Каталог | `/opt/vinoterra` | `/opt/vinoterra-web` |
| vhost | `sites-available/vino-terra.ru`, порт 80, `server_name vino-terra.ru` | `sites-available/vinoterra`, порт **8081**, `server_name _` |
| Неизвестный путь | `=404` | `try_files … /index.html` (SPA-заглушка, отвечает 200 главной страницей) |
| Прокси | `location /api/` | `location /api` (без слеша) |
| Пользователь службы | `vinoterra` | `root` |
| HTTPS | certbot | нет, 443 никто не слушает; домен обслуживается не с этой машины |

На той же машине живёт неродственный сайт `domrealt` — он занимает порт 80,
поэтому винотерра и оказалась на 8081. Порт открыт наружу в ufw, то есть сайт
доступен по адресу вида `http://<IP>:8081/`.

Что было исправлено на сервере 28.08.2026 (и перенесено в этот репозиторий):

- `chmod 600 backend/.env` — файл с `OPENAI_API_KEY` стоял `644`, то есть его
  читал любой пользователь сервера, включая `www-data` соседнего сайта;
- `TRUST_PROXY_HEADERS=1` в `.env` — переменной не было вообще;
- `proxy_set_header X-Forwarded-For $remote_addr;` вместо дописывания;
- запрет отдачи служебных файлов: `data/build.py` и `CONTRIBUTING.md`
  скачивались по HTTP (ключей в них нет, но лежать в вебе им незачем).

Проверка после любой правки vhost — все файлы сайта должны отвечать 200, а
служебные 403:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/data/world.json  # 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/data/build.py    # 403
```
