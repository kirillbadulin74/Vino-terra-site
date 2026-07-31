"""FastAPI-адаптер для того же RAG-ядра, которое использует Telegram-бот.

Отдаёт только API (/api/*): статику сайта в проде раздаёт nginx.
Каждый вопрос логируется в тот же SQLite (feedback_store, channel='web') —
конвейер «живая эксплуатация → регрессионные вопросы» общий для бота и сайта.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from src.feedback_store import FeedbackStore
from src.service import AssistantConfig, AssistantService, WebAnswer


def _csv_env(name: str, default: str) -> list[str]:
    return [item.strip().rstrip("/") for item in os.getenv(name, default).split(",") if item.strip()]


class HistoryMessage(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"user", "assistant"}:
            raise ValueError("Допустимы только роли user и assistant")
        return value


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1200)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=6)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Вопрос слишком короткий")
        return value


class SourceInfo(BaseModel):
    file: str
    section: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]
    interaction_id: int | None = None


class FeedbackRequest(BaseModel):
    interaction_id: int = Field(gt=0)
    vote: str

    @field_validator("vote")
    @classmethod
    def valid_vote(cls, value: str) -> str:
        if value not in {"up", "down"}:
            raise ValueError("Допустимы только оценки up и down")
        return value


class SlidingWindowLimiter:
    """Локальный лимитер: одного процесса на VPS достаточно; для нескольких
    реплик понадобился бы Redis."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - now) + 1)
                return False, retry_after
            events.append(now)
            return True, 0


mode = os.getenv("RAG_MODE", "hybrid")
if mode not in {"bm25", "vector", "hybrid"}:
    raise RuntimeError("RAG_MODE must be bm25, vector or hybrid")

service = AssistantService(
    AssistantConfig(
        mode=mode,  # type: ignore[arg-type]
        chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL",
            os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        ),
        top_k=int(os.getenv("RAG_TOP_K", "8")),
    )
)
limiter = SlidingWindowLimiter(
    limit=int(os.getenv("RATE_LIMIT_REQUESTS", "10")),
    window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
)

# Лог вопросов сайта — та же SQLite, что у Telegram-бота (channel='web').
# FEEDBACK_DB="" отключает лог (например, в тестах).
_feedback_db = os.getenv("FEEDBACK_DB", "feedback/feedback.db")
store: FeedbackStore | None = FeedbackStore(_feedback_db) if _feedback_db else None


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("SKIP_RAG_WARMUP", "0") != "1":
        await run_in_threadpool(service.start)
    yield


app = FastAPI(
    title="VINOTERRA Sommelier API",
    version="1.0.0",
    docs_url="/docs" if os.getenv("ENABLE_API_DOCS", "0") == "1" else None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_csv_env(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,https://vino-terra.ru,https://www.vino-terra.ru",
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def _client_key(request: Request) -> str:
    if os.getenv("TRUST_PROXY_HEADERS", "0") == "1":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok" if service.ready else "starting",
        "ready": service.ready,
        "chunks": service.chunk_count,
        "mode": service.config.mode,
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    allowed, retry_after = limiter.allow(_client_key(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Слишком много запросов. Попробуйте немного позже.",
            headers={"Retry-After": str(retry_after)},
        )
    started = time.monotonic()
    try:
        history = [item.model_dump() for item in payload.history]
        result: WebAnswer = await run_in_threadpool(service.answer, payload.question, history)
    except Exception as exc:
        # Текст исключения может содержать детали провайдера и не уходит клиенту.
        print(f"RAG request failed: {type(exc).__name__}: {exc}", flush=True)
        _log_safe(
            question=payload.question,
            answer="",
            latency_ms=int((time.monotonic() - started) * 1000),
            is_error=True,
        )
        raise HTTPException(status_code=502, detail="Не удалось получить ответ помощника.") from exc

    interaction_id = _log_safe(
        question=payload.question,
        answer=result.answer,
        sources=[f"{f} :: {s}" for f, s in result.sources],
        latency_ms=int((time.monotonic() - started) * 1000),
        llm_branch=result.llm_branch,
        retrieval_mode=result.retrieval_mode,
        is_refusal=result.is_refusal,
    )
    return ChatResponse(
        answer=result.answer,
        sources=[SourceInfo(file=f, section=s) for f, s in result.sources[:5]],
        interaction_id=interaction_id,
    )


@app.post("/api/feedback")
async def feedback(payload: FeedbackRequest) -> dict[str, bool]:
    if store is None:
        return {"ok": False}
    try:
        ok = await run_in_threadpool(store.set_feedback, payload.interaction_id, payload.vote)
    except Exception as exc:
        print(f"Feedback save failed: {exc}", flush=True)
        return {"ok": False}
    return {"ok": ok}


def _log_safe(
    *,
    question: str,
    answer: str,
    sources: list[str] | None = None,
    latency_ms: int | None = None,
    llm_branch: str | None = None,
    retrieval_mode: str | None = None,
    is_refusal: bool = False,
    is_error: bool = False,
) -> int | None:
    """Лог не должен помешать доставке ответа: любые ошибки — в stdout."""
    if store is None:
        return None
    try:
        return store.log_interaction(
            chat_id=0,  # веб-чат анонимный, сессии не различаем
            question=question,
            answer=answer,
            sources=sources,
            latency_ms=latency_ms,
            llm_branch=llm_branch,
            retrieval_mode=retrieval_mode,
            is_refusal=is_refusal,
            is_error=is_error,
            channel="web",
        )
    except Exception as exc:
        print(f"Feedback log failed: {exc}", flush=True)
        return None
