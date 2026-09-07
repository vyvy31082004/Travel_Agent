from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    PROJECT_ROOT
    / "alembic"
    / "versions"
    / "0008_result_item_presentation_state.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("result_item_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_result_item_presentation_migration_is_in_chain():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revisions = {script.revision for script in scripts.walk_revisions()}
    # 0008 is part of the migration chain (no longer the head after 0009).
    assert "0008_result_item_presentation" in revisions
    # There is a single head and it is the conversations migration.
    assert scripts.get_current_head() == "0009_conversations"


def test_result_item_presentation_migration_has_safe_backfill(monkeypatch):
    migration = _load_migration()
    calls: list[tuple[str, tuple, dict]] = []

    for operation in (
        "add_column",
        "execute",
        "alter_column",
        "create_unique_constraint",
    ):
        monkeypatch.setattr(
            migration.op,
            operation,
            lambda *args, _operation=operation, **kwargs: calls.append(
                (_operation, args, kwargs)
            ),
        )

    migration.upgrade()

    added = {
        args[1].name
        for operation, args, _ in calls
        if operation == "add_column"
    }
    assert added == {"api_position", "eligible"}

    statements = [
        str(args[0]) for operation, args, _ in calls if operation == "execute"
    ]
    assert any("SET api_position = position" in statement for statement in statements)

    api_position_alter = next(
        kwargs
        for operation, args, kwargs in calls
        if operation == "alter_column" and args[1] == "api_position"
    )
    display_position_alter = next(
        kwargs
        for operation, args, kwargs in calls
        if operation == "alter_column" and args[1] == "position"
    )
    assert api_position_alter["nullable"] is False
    assert display_position_alter["nullable"] is True
