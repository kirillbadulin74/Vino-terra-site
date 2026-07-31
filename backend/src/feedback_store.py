"""Лог взаимодействий бота + оценки пользователей (пожелание куратора после защиты).

Хранилище — один SQLite-файл. Назначение — не аналитика ради аналитики, а
продолжение методологии диплома «живая эксплуатация → регрессионные вопросы»:
каждый вопрос куратора/тестеров с ответом, источниками и веткой (main/fallback)
автоматически становится кандидатом в регрессионный набор. Оценки 👍/👎 и
отказы находятся SQL-запросом и указывают, где дополнять базу.

Пользовательских данных в смысле ПДн здесь нет: chat_id — технический
идентификатор, нужный, чтобы отличать сессии тестеров друг от друга.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                 -- UTC ISO-8601
    chat_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources TEXT,                     -- top-разделы поиска, по одному в строке
    latency_ms INTEGER,
    llm_branch TEXT,                  -- main | fallback
    retrieval_mode TEXT,              -- hybrid | bm25 (реально использованный)
    is_refusal INTEGER NOT NULL DEFAULT 0,  -- отказ «нет информации» / OOD
    is_error INTEGER NOT NULL DEFAULT 0,    -- ответ не сформирован (исключение)
    feedback TEXT,                    -- up | down | NULL (не оценён)
    channel TEXT NOT NULL DEFAULT 'telegram'  -- telegram | web
)
"""


class FeedbackStore:
    """Тонкая обёртка над SQLite. Telegram-бот однопоточный (long polling), а
    web_api вызывает log_interaction из threadpool FastAPI — поэтому соединение
    открывается с check_same_thread=False, а записи сериализуются внутренним
    локом. Для одного процесса этого достаточно; фоновый TypingIndicator в БД
    не пишет."""

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self.conn.execute(_SCHEMA)
            # Миграция БД, созданной дипломной версией (без колонки channel).
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(interactions)")}
            if "channel" not in columns:
                self.conn.execute(
                    "ALTER TABLE interactions ADD COLUMN channel TEXT NOT NULL DEFAULT 'telegram'"
                )
            self.conn.commit()

    def log_interaction(
        self,
        *,
        chat_id: int,
        question: str,
        answer: str,
        sources: list[str] | None = None,
        latency_ms: int | None = None,
        llm_branch: str | None = None,
        retrieval_mode: str | None = None,
        is_refusal: bool = False,
        is_error: bool = False,
        channel: str = "telegram",
    ) -> int:
        with self._lock:
            cursor = self.conn.execute(
                "INSERT INTO interactions (ts, chat_id, question, answer, sources, "
                "latency_ms, llm_branch, retrieval_mode, is_refusal, is_error, channel) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    chat_id,
                    question,
                    answer,
                    "\n".join(sources) if sources else None,
                    latency_ms,
                    llm_branch,
                    retrieval_mode,
                    int(is_refusal),
                    int(is_error),
                    channel,
                ),
            )
            self.conn.commit()
            return int(cursor.lastrowid)

    def set_feedback(self, interaction_id: int, vote: str) -> bool:
        """Записывает оценку up/down. False, если записи нет (например, БД
        пересоздали, а кнопка осталась под старым сообщением)."""
        if vote not in ("up", "down"):
            return False
        with self._lock:
            cursor = self.conn.execute(
                "UPDATE interactions SET feedback = ? WHERE id = ?",
                (vote, interaction_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def close(self) -> None:
        self.conn.close()
