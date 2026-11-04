"""The volatility pass: one isolated headless process per memory, after summarizing.

Volatility sets how long a session can act on a memory's claims before checking them
(verify-on-use, docs/direction.md): live 14 days, slow 30, stable 365. It is a separate pass
from the summary so each process makes one judgment, and so the same prompt classifies the
memories that never went through fast adoption.

Only memories with no way to know their volatility are classified: not one that states it,
nor one whose `status:` implies it (format-spec, "derived, not predicted"), nor a record,
which is never re-checked, nor a superseded memory, which is never edited. Verdicts are
cached under `.cache/migrate/volatility/` and land as-is, like adoption: a classification is
cheap to correct by hand, and a re-run only pays for files whose text changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_hybrid_memory import storegit
from claude_hybrid_memory.migrate.summarize import Job
from claude_hybrid_memory.store import Memory, scan_store

SUBDIR = "volatility"


@dataclass
class Target:
    rel: str
    territory: str
    mem: Memory


def targets(root: Path, territory: str | None = None) -> list[Target]:
    from claude_hybrid_memory.audit import superseded_paths

    mems, _ = scan_store(root)
    sup = superseded_paths(root)
    out = []
    for m in mems:
        if (m.path in sup or m.volatility is not None
                or str(m.meta.get("tier") or "") == "record"):
            continue
        if territory and not (m.container == territory
                              or m.container.startswith(territory + "/")):
            continue
        out.append(Target(str(m.path.relative_to(root)), m.container, m))
    return out


def job(t: Target) -> Job:
    return Job(t.rel, "volatility", f"territory: {t.territory}\n\nFILE:\n{t.mem.raw}")


def apply(root: Path, verdicts: dict[str, str]) -> tuple[list[str], storegit.Result | None]:
    """Write each verdict into its file's frontmatter, then one store commit. Returns the
    files left untouched because the field would not read back, and the commit result."""
    from claude_hybrid_memory.verified import set_field

    skipped = []
    for rel, vol in sorted(verdicts.items()):
        f = root / rel
        new = set_field(f.read_text(encoding="utf-8"), "volatility", vol)
        if new is None:
            skipped.append(rel)
            continue
        f.write_text(new, encoding="utf-8")
    n = len(verdicts) - len(skipped)
    if not n:
        return skipped, None
    return skipped, storegit.commit(root, "mem migrate volatility",
                                    subject=f"volatility on {n} memories (classified, as-is)")
