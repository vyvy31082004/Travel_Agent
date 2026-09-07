import asyncio
import selectors
import sys

from infrastructure.postgres import create_pool, AsyncPostgresSaver
from settings import get_settings
from agents.primary.agent import build_primary_graph

THREAD_ID = "d4a2954e-f613-4ce3-9c65-fb068e4a0485"


async def main():
    settings = get_settings()
    pool = create_pool(settings)
    await pool.open()
    try:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        graph = await build_primary_graph(
            checkpointer=checkpointer, repo=None, memory_service=None
        )
        snap = await graph.aget_state(
            {"configurable": {"thread_id": THREAD_ID}}
        )
        values = snap.values or {}
        summary = values.get("summary")
        msgs = values.get("messages") or []
        print("message_count:", len(msgs))
        print("summary is None:", summary is None)
        print("summary:")
        print(summary)
    finally:
        await pool.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        def _selector_loop() -> asyncio.AbstractEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

        asyncio.run(main(), loop_factory=_selector_loop)
    else:
        asyncio.run(main())