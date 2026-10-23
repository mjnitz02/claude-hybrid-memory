"""Cross-territory duplicate hints."""
from __future__ import annotations

import re

from claude_hybrid_memory.findings import INFO, Finding
from claude_hybrid_memory.store import Memory

STOP = set("the a an and or of to in for is are be with on at by not no never always "
           "prefer use using this that it its from as into over per".split())
OVERLAP = 0.55


def toks(s: str) -> set[str]:
    """The words a description overlap is measured on."""
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in STOP}


def check_dup(mems: list[Memory]) -> list[Finding]:
    """Conservative duplicate and standing-candidate hints. Hints, never verdicts."""
    out = []
    items = [(m, toks(str(m.meta.get("description") or ""))) for m in mems]
    items = [(m, t) for m, t in items if len(t) >= 4]
    seen = set()
    for i, (m1, t1) in enumerate(items):
        for m2, t2 in items[i + 1:]:
            if m1.container == m2.container:
                continue
            j = len(t1 & t2) / len(t1 | t2)
            if j >= OVERLAP:
                key = tuple(sorted([str(m1.path), str(m2.path)]))
                if key in seen:
                    continue
                seen.add(key)
                out.append(Finding(INFO, "possible-duplicate", str(m1.path),
                                   f"~{j:.0%} description overlap with {m2.path} "
                                   f"({m1.container} vs {m2.container}) - hint, verify by "
                                   "reading both"))
    # A word-frequency "standing candidate" detector lived here and was deleted. It
    # returned words like "how", "repo", "user" and "2026": common vocabulary, not
    # directives. The real signal that motivated it ("use uv" in 11 silos) is a phrase in a
    # description, which possible-duplicate above already surfaces. A weak detector is
    # worse than none (docs/design.md, Self-verification), so this one is gone, not tuned.
    return out
