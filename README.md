# ВИНОТЕРРА — сайт-путеводитель по вину с ИИ-помощником

Сайт-путеводитель по миру вина с ИИ-помощником «Нейро-сомелье» прямо на сайте
и в Telegram (@VinoTerra_AI_bot). Это версия для развёртывания на собственном
VPS: статика + Python-бэкенд. Публикация на собственном домене пока не
настроена; статическая версия сайта без чата опубликована отдельно на
[GitHub Pages](https://kirillbadulin74.github.io/Vinoterra-site-html/).

```
frontend/   статика сайта (HTML/CSS/JS + данные data/*.json → wine-data.js)
backend/    Python: RAG-ядро (hybrid BM25+vector), FastAPI веб-API, Telegram-бот
deploy/     nginx-конфиг, systemd-юниты, DEPLOY.md — инструкция развёртывания
```

## Как это работает

- **Сайт** — статические страницы; карточки стран/сортов рендерятся из
  `frontend/data/wine-data.js`. Правки контента: `frontend/CONTRIBUTING.md`.
- **Нейро-сомелье** — единое RAG-ядро (`backend/src/`) на базе знаний
  `backend/knowledge_base/` (5 файлов, 2829 чанков). Два транспорта:
  - `src/web_api.py` — FastAPI: `/api/chat`, `/api/feedback`, `/api/health`
    (чат-виджет на сайте);
  - `src/telegram_bot.py` — Telegram-бот (long polling).
- Поиск hybrid (BM25 + вектор, RRF); при сбое эмбеддингов деградирует до BM25,
  при сбое OpenAI генерация уходит на фоллбэк DeepSeek (если задан ключ).
- Все вопросы и оценки 👍/👎 обоих каналов пишутся в SQLite
  `backend/feedback/feedback.db` (колонка `channel`: web | telegram).

## Локальный запуск

```bash
# API (из backend/; hybrid требует OPENAI_API_KEY в .env, офлайн-вариант — RAG_MODE=bm25)
cd backend && pip install -r requirements.txt && python run_web_api.py

# сайт (из frontend/)
python -m http.server 8000
# открыть http://127.0.0.1:8000 — чат сам найдёт API на 127.0.0.1:8080
```

## Развёртывание на сервере

Полная инструкция — `deploy/DEPLOY.md` (Ubuntu + nginx + systemd + certbot).
