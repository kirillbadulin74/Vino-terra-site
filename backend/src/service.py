"""Общий прикладной слой VINOTERRA для HTTP API и других интерфейсов.

Один загруженный RAG обслуживает и сайт (web_api), и, при желании, другие
транспорты. Ядро (src/rag.py) — то же, что у Telegram-бота, поэтому веб-чат и
бот отвечают одинаково. Веб-слой передаёт историю как список dict
(`{"role","content"}`), а ядро ждёт пары (вопрос, ответ) — конвертация здесь.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from src.assistant_factory import build_assistant
from src.rag import RAGAnswer, RetrievalMode, WineRAGAssistant


BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AssistantConfig:
    base_dir: Path = BACKEND_DIR / "knowledge_base"
    vector_cache: Path = BACKEND_DIR / "vector_index"
    mode: RetrievalMode = "hybrid"
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 500
    chunk_overlap: int = 100
    top_k: int = 8
    temperature: float = 0.0


@dataclass
class WebAnswer:
    """Ответ веб-чата + метаданные для лога (аналог BotAnswer у бота)."""

    answer: str
    sources: list[tuple[str, str]] = field(default_factory=list)  # (file, section)
    llm_branch: str = "main"
    retrieval_mode: str | None = None
    is_refusal: bool = False


def _history_to_pairs(history: list[dict[str, str]] | None) -> list[tuple[str, str]]:
    """Список сообщений веб-чата → пары (вопрос_пользователя, ответ_ассистента).

    Ядро использует пары для конденсации follow-up вопросов. Собираем пары по
    порядку: каждый user-месседж, за которым следует assistant-ответ. Незавершённые
    реплики (user без ответа, например текущий вопрос) игнорируются.
    """
    if not history:
        return []
    pairs: list[tuple[str, str]] = []
    pending_user: str | None = None
    for item in history:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            pending_user = content
        elif role == "assistant" and pending_user is not None:
            pairs.append((pending_user, content))
            pending_user = None
    return pairs


class AssistantService:
    """Один загруженный RAG и единая точка ответа для всех транспортов."""

    def __init__(self, config: AssistantConfig) -> None:
        self.config = config
        self._assistant: WineRAGAssistant | None = None
        self._chunk_count = 0
        self._init_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._assistant is not None

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    def start(self) -> None:
        if self._assistant is not None:
            return
        with self._init_lock:
            if self._assistant is not None:
                return
            self._assistant, self._chunk_count = build_assistant(
                base_dir=self.config.base_dir,
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                chat_model=self.config.chat_model,
                mode=self.config.mode,
                vector_cache=self.config.vector_cache,
                embedding_model=self.config.embedding_model,
                temperature=self.config.temperature,
            )

    def answer(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> WebAnswer:
        self.start()
        assert self._assistant is not None
        result: RAGAnswer = self._assistant.answer(
            question,
            mode=self.config.mode,
            top_k=self.config.top_k,
            history=_history_to_pairs(history),
        )
        return _to_web_answer(result)


def _to_web_answer(result: RAGAnswer) -> WebAnswer:
    sources: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in result.results:
        key = (item.source_file, item.section_path)
        if key not in seen:
            seen.add(key)
            sources.append(key)
    # Отказ («нет информации» / OOD-гард) определяем по канонической фразе —
    # обе ветки rag.py используют её дословно (тот же приём, что в telegram_bot).
    is_refusal = "нет релевантной информации" in result.answer
    return WebAnswer(
        answer=result.answer,
        sources=sources,
        llm_branch=result.llm_branch,
        retrieval_mode=result.retrieval_mode_used or result.mode,
        is_refusal=is_refusal,
    )
