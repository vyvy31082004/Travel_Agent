from __future__ import annotations

import json
from pathlib import Path


def test_committed_notebooks_have_no_outputs_or_execution_counts():
    dirty: list[str] = []
    for notebook_path in Path("src/notebooks").glob("*.ipynb"):
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        for index, cell in enumerate(notebook.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            if cell.get("outputs") or cell.get("execution_count") is not None:
                dirty.append(f"{notebook_path}:cell-{index}")

    assert dirty == []
