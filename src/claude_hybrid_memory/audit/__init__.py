"""The audit: mechanical checks against docs/format-spec.md.

Each module is one concern. `run_all` is `mem audit`, in the order the report has always
been assembled.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from claude_hybrid_memory.audit.budget import check_budget
from claude_hybrid_memory.audit.dup import check_dup
from claude_hybrid_memory.audit.exports import check_exports
from claude_hybrid_memory.audit.freshness import check_freshness
from claude_hybrid_memory.audit.links import check_links, check_router_drift
from claude_hybrid_memory.audit.migration import check_silos
from claude_hybrid_memory.audit.relations import check_chains, check_relations, store_graph
from claude_hybrid_memory.audit.secrets import check_secrets
from claude_hybrid_memory.audit.split import check_split
from claude_hybrid_memory.audit.structure import check_structure
from claude_hybrid_memory.events import read_counts
from claude_hybrid_memory.findings import Finding
from claude_hybrid_memory.store import Memory

__all__ = [
    "check_budget", "check_chains", "check_dup", "check_exports", "check_freshness", "check_links",
    "check_relations", "check_router_drift", "check_secrets", "check_silos", "check_split",
    "check_structure", "run_all", "superseded_paths",
]


def superseded_paths(root: Path) -> frozenset:
    """Absolute paths of every superseded memory, for the checks that must exempt them."""
    if not root.is_dir():
        return frozenset()
    return frozenset(root / p for p in store_graph(root).superseded())


def run_all(mems: list[Memory], routers: dict, root: Path, legacy: Path,
            today: dt.date) -> list[Finding]:
    from claude_hybrid_memory import render

    sup = superseded_paths(root)
    return (check_structure(mems) + check_links(mems, routers, sup)
            + check_router_drift(mems, routers, sup) + check_exports(root, routers)
            + check_relations(mems) + check_chains(root, routers)
            + check_freshness(mems, today, False) + check_budget(root, mems)
            + check_silos(legacy, root) + check_dup(mems)
            + check_secrets(root, [m for m in mems if m.scope == "legacy"])
            + check_split(mems, read_counts(root), root) + render.check(root))
