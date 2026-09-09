"""Chạy & test memory worker ở local giống production (Windows/Linux/macOS).

Gộp 3 việc vào một file:
  1. Vòng lặp "cron" viết sẵn: lặp lại việc xử lý job theo chu kỳ, đúng như
     Azure Container Apps Job gọi `--once` mỗi phút (mặc định `--interval 60`).
     KHÔNG còn cờ `--once` — bản thân script chính là cron.
  2. Cờ `--use-api`: bật/tắt gọi Gemini thật.
       - CÓ  `--use-api`: dùng đúng cấu hình production trong .env
         (langmem + trustmem + transition llm + embedding). Tốn API.
       - KHÔNG (mặc định): ép deterministic/lexical + tắt embedding → KHÔNG
         gọi Gemini, không tốn tiền. Chỉ test cơ chế queue/worker/commit.
  3. Cờ `--seed`: chèn một memory job giả vào `memory_jobs` rồi thoát, để có
     việc cho worker nhặt (thay cho file seed riêng trước đây).

`src/memory_worker.py` dùng `asyncio.run(...)`; trên Windows + Python 3.12
asyncio ép ProactorEventLoop — không tương thích psycopg async pool. Script này
luôn dùng SelectorEventLoop nên chạy được ở mọi hệ điều hành.

Ví dụ dùng (từ thư mục gốc repo, đã có .env):
    # 1) Tạo một job giả (không tốn API)
    python scripts/run_memory_worker_local.py --seed

    # 2) Chạy cron worker, KHÔNG tốn API, mỗi 60s một nhịp
    python scripts/run_memory_worker_local.py

    # 3) Chạy cron worker GIỐNG PRODUCTION (Gemini thật), mỗi 60s
    python scripts/run_memory_worker_local.py --use-api

    # 4) Test nhanh: chạy 3 nhịp rồi tự dừng, nhịp 5s
    python scripts/run_memory_worker_local.py --interval 5 --max-ticks 3

    # 5) Backfill embeddings một mẻ (cần API) rồi thoát
    python scripts/run_memory_worker_local.py --use-api --backfill-embeddings
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import selectors
import sys
import time
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

logger = logging.getLogger("run_memory_worker_local")


def _selector_run(coro):
    """Chạy một coroutine trên SelectorEventLoop (an toàn cho psycopg/Windows)."""
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _apply_no_api_env() -> None:
    """Ép chế độ deterministic/lexical + tắt embedding TRƯỚC khi settings load.

    Đặt trực tiếp vào os.environ nên get_settings() (có lru_cache) sẽ đọc đúng.
    """
    os.environ["LONG_TERM_MEMORY_EXTRACTOR"] = "deterministic"
    os.environ["LONG_TERM_MEMORY_VERIFIER"] = "deterministic"
    os.environ["LONG_TERM_MEMORY_TRANSITION_PATH"] = "lexical"
    os.environ["LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED"] = "false"


def _load_settings():
    from settings import get_settings

    # settings dùng lru_cache; xoá để chắc chắn đọc env vừa đặt ở trên.
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    return get_settings()


async def _build_worker(postgres, settings, *, use_api: bool):
    from memory.commit import MemoryCommitAdapter
    from memory.embeddings import MemoryEmbeddingService
    from memory.verifier import build_memory_verifier
    from memory.worker import MemoryWorker
    from repositories.long_term_memory import PostgresLongTermMemoryRepository

    repository = PostgresLongTermMemoryRepository(postgres.pool)
    # No-API: KHÔNG tạo embedding service -> commit adapter bỏ qua embedding hẳn.
    embedding_service = MemoryEmbeddingService(settings=settings) if use_api else None
    worker = MemoryWorker(
        pool=postgres.pool,
        settings=settings,
        repository=repository,
        commit_adapter=MemoryCommitAdapter(
            repository=repository,
            verifier=build_memory_verifier(settings),
            embedding_service=embedding_service,
        ),
        embedding_service=embedding_service,
    )
    return worker


async def _cron_loop(*, use_api: bool, interval: int, max_ticks: int) -> None:
    """Đóng vai cron: mỗi nhịp xử lý MỘT job (như production `--once`), rồi ngủ."""
    from infrastructure.postgres import open_postgres

    settings = _load_settings()
    mode = "API thật (production)" if use_api else "deterministic (KHÔNG API)"
    logger.info(
        "cron worker khởi động | mode=%s | interval=%ss | max_ticks=%s",
        mode,
        interval,
        max_ticks or "vô hạn",
    )
    async with open_postgres(settings) as postgres:
        worker = await _build_worker(postgres, settings, use_api=use_api)
        tick = 0
        while True:
            tick += 1
            result = await worker.process_next()
            logger.info("tick %s -> %s", tick, result)
            if max_ticks and tick >= max_ticks:
                logger.info("đạt max_ticks=%s, dừng.", max_ticks)
                return
            time.sleep(interval)


async def _backfill_once(*, use_api: bool) -> None:
    """Chạy một mẻ backfill embeddings rồi thoát (cần API)."""
    import memory_worker

    if not use_api:
        raise SystemExit("--backfill-embeddings cần --use-api (phải gọi Gemini để nhúng).")
    await memory_worker._backfill_embeddings()


async def _seed_job() -> None:
    """Chèn một memory job giả vào hàng đợi để worker có việc nhặt."""
    from infrastructure.postgres import open_postgres
    from repositories.long_term_memory import PostgresLongTermMemoryRepository
    from services.auth import AuthRepository
    from services.long_term_memory import memory_job_idempotency_key

    settings = _load_settings()
    async with open_postgres(settings) as postgres:
        auth = AuthRepository(postgres.pool)
        repo = PostgresLongTermMemoryRepository(postgres.pool)

        email = f"worker-test-{uuid.uuid4().hex[:8]}@example.com"
        user = await auth.create_user(
            email=email, full_name="Worker Test", password="password123"
        )
        thread_id = f"worker-test-{uuid.uuid4().hex[:8]}"
        final_message_id = "ai-1"
        messages = [
            {"type": "human", "content": "Tôi thích bay thẳng, không nối chuyến."},
            {"type": "ai", "content": "Đã ghi nhận bạn thích bay thẳng."},
        ]
        key = memory_job_idempotency_key(
            user_id=user.user_id,
            thread_id=thread_id,
            final_message_id=final_message_id,
            checkpoint_id=None,
        )
        job = await repo.enqueue_memory_job(
            user_id=user.user_id,
            thread_id=thread_id,
            idempotency_key=key,
            final_message_id=final_message_id,
            checkpoint_id=None,
            messages=messages,
            metadata={"seeded": True},
        )
        logger.info("seeded user_id=%s", user.user_id)
        logger.info("seeded thread_id=%s", thread_id)
        logger.info("seeded job_id=%s created=%s", job.job_id, job.created)
        logger.info("Giờ chạy: python scripts/run_memory_worker_local.py")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cron worker + seed cho long-term memory (test local)"
    )
    parser.add_argument(
        "--use-api",
        action="store_true",
        help="Dùng Gemini thật theo .env (tốn API). Mặc định: deterministic, không API.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Số giây giữa các nhịp cron (mặc định 60, giống production */1).",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=0,
        help="Dừng sau N nhịp (0 = chạy vô hạn cho tới Ctrl+C).",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Chèn một memory job giả vào hàng đợi rồi thoát.",
    )
    parser.add_argument(
        "--backfill-embeddings",
        action="store_true",
        help="Chạy một mẻ backfill embeddings rồi thoát (cần --use-api).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # No-API: đặt env trước khi bất kỳ settings/module nào load.
    if not args.use_api:
        _apply_no_api_env()

    run = _selector_run if sys.platform == "win32" else asyncio.run

    if args.seed:
        run(_seed_job())
        return
    if args.backfill_embeddings:
        run(_backfill_once(use_api=args.use_api))
        return
    run(_cron_loop(use_api=args.use_api, interval=args.interval, max_ticks=args.max_ticks))


if __name__ == "__main__":
    main()
