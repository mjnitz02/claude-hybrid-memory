"""Exports: a territory's EXPORTS.md against the copies inlined into its consumers."""
from __future__ import annotations

import re
from pathlib import Path

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding


def _bullets(text: str) -> list[str]:
    """Body bullets, minus frontmatter, comments and headings."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")) and not line.startswith(("- <", "* <")):
            out.append(re.sub(r"\s+", " ", line[2:]).strip().rstrip("."))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def check_exports(root: Path, routers: dict) -> list[Finding]:
    """A territory's EXPORTS.md is the source of truth; router copies are derived.

    Where an export lands depends on its reach: utility/* exports bind everywhere and go
    in ROUTER.md; chain/* exports only matter one layer down and are inlined into the
    consuming territory's MEMORY.md. This reports copies that have drifted from source.
    """
    out: list[Finding] = []
    tdir = root / "territories"
    if not tdir.is_dir():
        return out
    global_router = ""
    gr = root / "ROUTER.md"
    if gr.is_file():
        global_router = gr.read_text(encoding="utf-8", errors="replace")

    for exp in sorted(tdir.rglob("EXPORTS.md")):
        terr = str(exp.parent.relative_to(tdir))
        facts = _bullets(exp.read_text(encoding="utf-8", errors="replace"))
        if not facts:
            out.append(Finding(WARN, "exports-empty", f"{terr}/EXPORTS.md",
                               "declares no exports; either fill it in or delete it"))
            continue
        if len(facts) > 6:
            out.append(Finding(WARN, "exports-too-many", f"{terr}/EXPORTS.md",
                               f"{len(facts)} exports; more than ~6 usually means the "
                               "territory boundary is in the wrong place"))
        # where should these appear?
        if terr.startswith("utility/"):
            targets = [("ROUTER.md", global_router)]
        else:
            consumers = [c for c, r in routers.items()
                         if _norm(str(r.meta.get("consumes") or "")) == _norm(terr)]
            if not consumers:
                out.append(Finding(INFO, "exports-no-consumer", f"{terr}/EXPORTS.md",
                                   "no territory declares `consumes: " + terr + "`; "
                                   "nothing inlines these"))
                continue
            targets = [(f"{c}/MEMORY.md", routers[c].raw) for c in consumers]
        for tname, ttext in targets:
            tnorm = _norm(ttext)
            for fact in facts:
                if _norm(fact)[:60] not in tnorm:
                    out.append(Finding(ERROR, "export-not-inlined", tname,
                                       f"missing export from {terr}: {fact[:90]!r}"))
    return out
