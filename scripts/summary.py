"""In summary + số lượng message của một conversation thread (công cụ debug).

Đọc state của LangGraph checkpointer theo `thread_id` và in ra `summary` cùng
số message hiện có. Dùng để soi nhanh một thread khi debug (local hoặc, khi cần,
qua `az containerapp exec` trên production — script tự đọc DATABASE_URL từ env).

Cách dùng (từ thư mục gốc repo, đã có .env):
    python scripts/summary.py <thread_id>
    python scripts/summary.py <thread_id> --full        # in toàn bộ summary, không cắt
    python scripts/summary.py <thread_id> --show-messages 5   # in 5 message cuối

Ví dụ:
    python scripts/summary.py d4a2954e-f613-4ce3-9c65-fb068e4a0485

Trên Windows script tự dùng SelectorEventLoop để tương thích psycopg async pool.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import selectors
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


async def _run(thread_id: str, *, full: bool, show_messages: int) -> int:
    from agents.primary.agent import build_primary_graph
    from infrastructure.postgres import AsyncPostgresSaver, create_pool
    from settings import get_settings

    settings = get_settings()
    pool = create_pool(settings)
    await pool.open()
    try:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        graph = await build_primary_graph(
            checkpointer=checkpointer, repo=None, memory_service=None
        )
        snapshot = await graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        values = snapshot.values or {}
        messages = values.get("messages") or []
        summary = values.get("summary")

        print(f"thread_id: {thread_id}")
        print(f"message_count: {len(messages)}")
        print(f"summary is None: {summary is None}")
        if summary is not None:
            text = str(summary)
            if not full and len(text) > 2000:
                print("summary (truncated to 2000 chars; use --full for all):")
                print(text[:2000] + "…")
            else:
                print("summary:")
                print(text)

        if show_messages > 0 and messages:
            print(f"\nlast {show_messages} message(s):")
            for message in messages[-show_messages:]:
                role = getattr(message, "type", "?")
                content = getattr(message, "content", "")
                snippet = str(content).replace("\n", " ")
                if len(snippet) > 200:
                    snippet = snippet[:200] + "…"
                print(f"  [{role}] {snippet}")

        # Non-zero exit if the thread has no state at all (helps scripting).
        return 0 if snapshot.values else 2
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="In summary + message count của một conversation thread."
    )
    parser.add_argument("thread_id", help="Thread id cần soi (configurable.thread_id).")
    parser.add_argument(
        "--full",
        action="store_true",
        help="In toàn bộ summary thay vì cắt bớt.",
    )
    parser.add_argument(
        "--show-messages",
        type=int,
        default=0,
        metavar="N",
        help="In N message cuối cùng của thread (mặc định 0 = không in).",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        try:
            asyncio.set_event_loop(loop)
            code = loop.run_until_complete(
                _run(args.thread_id, full=args.full, show_messages=args.show_messages)
            )
        finally:
            loop.close()
    else:
        code = asyncio.run(
            _run(args.thread_id, full=args.full, show_messages=args.show_messages)
        )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
