from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig


def with_trace_config(
    config: RunnableConfig | None = None,
    *,
    run_name: str | None = None,
    tags: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RunnableConfig:
    """Return a RunnableConfig enriched with LangSmith trace metadata."""
    next_config: dict[str, Any] = dict(config or {})

    if run_name:
        next_config["run_name"] = run_name

    merged_tags = list(next_config.get("tags") or [])
    for tag in tags or ():
        if tag not in merged_tags:
            merged_tags.append(tag)
    if merged_tags:
        next_config["tags"] = merged_tags

    merged_metadata = dict(next_config.get("metadata") or {})
    if metadata:
        merged_metadata.update(
            {key: value for key, value in metadata.items() if value is not None}
        )
    if merged_metadata:
        next_config["metadata"] = merged_metadata

    return next_config
