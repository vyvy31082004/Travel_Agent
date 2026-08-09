from __future__ import annotations

import argparse
import asyncio
import logging

from infrastructure.postgres import open_postgres
from memory.commit import MemoryCommitAdapter
from memory.embeddings import MemoryEmbeddingService, memory_content_hash
from memory.verifier import DeterministicMemoryVerifier
from memory.worker import MemoryWorker
from repositories.long_term_memory import (
    MemoryEmbeddingRecord,
    PostgresLongTermMemoryRepository,
)
from settings import get_settings


async def _run_once() -> None:
    settings = get_settings()
    async with open_postgres(settings) as postgres:
        repository = PostgresLongTermMemoryRepository(postgres.pool)
        embedding_service = MemoryEmbeddingService(settings=settings)
        worker = MemoryWorker(
            pool=postgres.pool,
            settings=settings,
            repository=repository,
            commit_adapter=MemoryCommitAdapter(
                repository=repository,
                verifier=DeterministicMemoryVerifier(),
                embedding_service=embedding_service,
            ),
        )
        result = await worker.process_next()
        logging.info("memory worker result: %s", result)

async def _backfill_embeddings() -> None:
    settings = get_settings()
    async with open_postgres(settings) as postgres:
        repository = PostgresLongTermMemoryRepository(postgres.pool)
        embedding_service = MemoryEmbeddingService(settings=settings)
        memories = await repository.find_memories_missing_current_embedding(
            embedding_model=embedding_service.model,
            embedding_dims=embedding_service.dims,
            limit=settings.long_term_memory_embedding_backfill_batch_size,
        )
        processed = 0
        failed = 0
        for memory in memories:
            if not memory.memory_id:
                continue
            try:
                embedding = await embedding_service.embed_memory(memory)
                await repository.upsert_memory_embedding(
                    MemoryEmbeddingRecord(
                        memory_id=memory.memory_id,
                        embedding=embedding,
                        embedding_model=embedding_service.model,
                        embedding_dims=embedding_service.dims,
                        content_hash=memory_content_hash(
                            memory,
                            model=embedding_service.model,
                        ),
                    )
                )
                processed += 1
            except Exception as exc:
                failed += 1
                logging.warning(
                    "memory embedding backfill failed for %s: %s",
                    memory.memory_id,
                    exc,
                )
        logging.info(
            "memory embedding backfill processed %s memories, failed %s",
            processed,
            failed,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Process long-term memory jobs")
    parser.add_argument("--once", action="store_true", help="Process one pending job")
    parser.add_argument(
        "--backfill-embeddings",
        action="store_true",
        help="Embed one batch of active memories missing current embeddings",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once == args.backfill_embeddings:
        raise SystemExit("Choose exactly one mode: --once or --backfill-embeddings")
    if args.backfill_embeddings:
        asyncio.run(_backfill_embeddings())
    else:
        asyncio.run(_run_once())


if __name__ == "__main__":
    main()
