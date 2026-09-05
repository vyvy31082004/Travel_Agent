from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# Result Store uses "tour" for excursion search tools; branch domain is "excursion".
_VISIBLE_RESULT_DOMAIN_ALIASES: dict[str, set[str]] = {
    "excursion": {"excursion", "tour"},
    "tour": {"excursion", "tour"},
}


def _visible_result_matches_branch(entry_domain: str | None, branch_domain: str) -> bool:
    if not entry_domain:
        return True
    if entry_domain == branch_domain:
        return True
    aliases = _VISIBLE_RESULT_DOMAIN_ALIASES.get(branch_domain, {branch_domain})
    return entry_domain in aliases


@dataclass
class DomainBranchResult:
    domain: str
    options: list[dict[str, Any]] = field(default_factory=list)
    applied_constraints: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""
    domain_action: str | None = None
    memory_applicability: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def build_domain_branch_result(
    *,
    domain: str,
    summary: str,
    turn_constraints: list[str] | None = None,
    domain_memory_context: str | None = None,
    domain_soft_memory_context: str | None = None,
    domain_action: str | None = None,
    memory_applicability: list[dict[str, Any]] | None = None,
    visible_results: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> DomainBranchResult:
    applied = list(turn_constraints or [])
    if domain_memory_context:
        for line in domain_memory_context.splitlines():
            text = line.strip()
            if text and text not in applied:
                applied.append(text)
    if domain_soft_memory_context:
        for line in domain_soft_memory_context.splitlines():
            text = line.strip()
            if text and text not in applied:
                applied.append(f"(soft) {text}")

    options: list[dict[str, Any]] = []
    for entry in (visible_results or {}).values():
        if not isinstance(entry, dict):
            continue
        if not _visible_result_matches_branch(entry.get("domain"), domain):
            continue
        options.append(
            {
                "search_id": entry.get("search_id"),
                "displayed_item_ids": entry.get("displayed_item_ids") or [],
                "labels": entry.get("labels") or [],
            }
        )

    branch_warnings = list(warnings or [])
    if not summary.strip():
        branch_warnings.append("Domain assistant returned empty summary.")

    return DomainBranchResult(
        domain=domain,
        options=options,
        applied_constraints=applied,
        warnings=branch_warnings,
        summary=summary.strip(),
        domain_action=domain_action,
        memory_applicability=list(memory_applicability or []),
    )
