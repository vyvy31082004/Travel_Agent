from __future__ import annotations

import argparse
import asyncio
import logging

from infrastructure.postgres import open_postgres
from memory.commit import MemoryCommitAdapter
from memory.verifier import DeterministicMemoryVerifier
from memory.worker import MemoryWorker
from repositories.long_term_memory import PostgresLongTermMemoryRepository
from settings import get_settings


async def _run_once() -> None:
    settings = get_settings()
    async with open_postgres(settings) as postgres:
        repository = PostgresLongTermMemoryRepository(postgres.pool)
        worker = MemoryWorker(
            pool=postgres.pool,
            settings=settings,
            repository=repository,
            commit_adapter=MemoryCommitAdapter(
                repository=repository,
                verifier=DeterministicMemoryVerifier(),
            ),
        )
        result = await worker.process_next()
        logging.info("memory worker result: %s", result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process long-term memory jobs")
    parser.add_argument("--once", action="store_true", help="Process one pending job")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not args.once:
        raise SystemExit("Only --once mode is available in this baseline worker")
    asyncio.run(_run_once())


if __name__ == "__main__":
    main()
