"""Split candidates and accretion: files acting as logs instead of memories (direction §9).

There is no read gate, by decision (direction §16.2). A large file is a maintenance question with
a *why* behind it, so it surfaces here and in the retro rather than at read time.
"""
from __future__ import annotations

from collections import Counter

from claude_hybrid_memory.findings import INFO, WARN, Finding
from claude_hybrid_memory.spec import ACCRETION_RE
from claude_hybrid_memory.store import Memory

# The 95th percentile of a real store's 297 territory files on 2026-10-21 (median 3.4 KB,
# max 38.8 KB): 14 files, ~2,500 tokens and up, to read for what is usually one paragraph.
SPLIT_BYTES = 10 * 1024


def check_split(mems: list[Memory], reads: Counter, root) -> list[Finding]:
    """Rank oversized territory files by size x (1 + accretion markers) x (1 + reads)."""
    terr = [m for m in mems if m.scope == "store" and m.container != "standing"]
    out = []
    accreted = [m for m in terr if ACCRETION_RE.search(m.raw)]
    if accreted:
        out.append(Finding(INFO, "accretion", str(root),
                           f"{len(accreted)} of {len(terr)} territory files carry accretion "
                           "markers (read bottom-up, history below, CORRECTION, SUPERSEDED): "
                           "mutable files acting as logs. Split into state + records when "
                           "next touched (direction §15 Phase 3)."))
    big = []
    for m in terr:
        size = len(m.raw.encode())
        if size > SPLIT_BYTES:
            rel = str(m.path.relative_to(root)) if root in m.path.parents else str(m.path)
            markers, n_reads = len(ACCRETION_RE.findall(m.raw)), reads.get(rel, 0)
            big.append((size * (1 + markers) * (1 + n_reads), m, size, markers, n_reads))
    big.sort(key=lambda x: -x[0])
    for rank, (_, m, size, markers, n_reads) in enumerate(big, 1):
        out.append(Finding(WARN, "split-candidate", str(m.path),
                           f"#{rank} of {len(big)}: {size / 1024:.1f} KB (~{size // 4:,} tokens), "
                           f"{markers} accretion marker(s), read {n_reads}x in events. Why is "
                           "it this big, and should it be separate memories?"))
    return out
