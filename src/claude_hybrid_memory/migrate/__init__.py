"""Fast adoption (docs/fast-adoption.md): inventory, summarize, map, land, refine.

Everything here writes under `<store>/.cache/migrate/`, which is derived and gitignored:
it can all be rebuilt from the silos, the store and the summarizer.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# Prompts `mem` hands to `claude -p`. Not `agents/`: a plugin would load that as subagents.
PROMPTS = REPO / "prompts"


def workdir(root: Path) -> Path:
    return root / ".cache" / "migrate"
