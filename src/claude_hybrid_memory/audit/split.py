"""Split candidates and accretion: files acting as logs instead of memories (direction §9).

There is no read gate, by decision (direction §16.2). A large file is a maintenance question with
a *why* behind it, so it surfaces here and in the retro rather than at read time.

Sometimes the answer is that the file is fine at that size: splitting it would cut one
argument in half. The user records that with `mem no-split <slug> -m REASON`. The command writes
`splittable: "no until 20 KB: REASON"` into the file's frontmatter, with the ceiling set to
the next 10 KB step above the file's size when they answered. The decision then lives on the
file: it moves with `mem mv`, any session reading the file can see it, and the retro does not
have to compare `mem audit` against RETRO.md. Under its ceiling the file is counted on one INFO
line; past it, the question comes back once, with the old reason attached.

Declines used to be `refine:split-candidate:<path>` keys in RETRO.md. Those suppressed only
the refine queue, never `mem audit`, and stopped matching once the file moved. A file that
still has only one of those keys is reported as `split-decline-legacy`, with the
`mem no-split` command that migrates it.
"""

from __future__ import annotations

import re
import shlex
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from claude_hybrid_memory.audit.freshness import is_live
from claude_hybrid_memory.findings import INFO, WARN, Finding
from claude_hybrid_memory.spec import ACCRETION_RE
from claude_hybrid_memory.store import Memory

# The 95th percentile of a real store's 297 territory files on 2026-10-21 (median 3.4 KB,
# max 38.8 KB): 14 files, ~2,500 tokens and up, to read for what is usually one paragraph.
SPLIT_BYTES = 10 * 1024
# A declined file comes back each time it grows into the next step.
CEILING_STEP_KB = 10

_NO_RE = re.compile(r"\s*no\b(?:\s+until\s+(\d+)\s*KB\b)?\s*[:—–-]?\s*(.*)", re.I | re.S)
_LEGACY_RE = re.compile(r"`refine:split-candidate:([^`]+)`\s*[—–-]*\s*(.*)")


class NoSplit(NamedTuple):
    """A parsed `splittable: no ...`. `ceiling_kb` is None when someone wrote a bare `no`
    by hand, with no ceiling: that is not honoured (see check_split)."""

    ceiling_kb: int | None
    reason: str


def no_split(meta: dict) -> NoSplit | None:
    """The `splittable:` decline on a memory, or None if it has none. YAML reads a bare
    `no` as False, so that counts as a decline too."""
    v = meta.get("splittable")
    if v is False:
        return NoSplit(None, "")
    m = _NO_RE.fullmatch(str(v)) if isinstance(v, str) else None
    if not m:
        return None
    return NoSplit(int(m.group(1)) if m.group(1) else None, m.group(2).strip())


def ceiling_for(size: int) -> int:
    """The next 10 KB step strictly above `size` bytes, in KB: 15 KB -> 20, 21 KB -> 30."""
    return (size // (CEILING_STEP_KB * 1024) + 1) * CEILING_STEP_KB


def field_value(size: int, reason: str) -> str:
    return f"no until {ceiling_for(size)} KB: {' '.join(reason.split())}"


def legacy_declines(root: Path) -> dict[str, str]:
    """Store-relative path -> reason for each `refine:split-candidate:` key in RETRO.md."""
    f = root / "RETRO.md"
    if not f.is_file():
        return {}
    out = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        m = _LEGACY_RE.search(line)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def _rel(m: Memory, root) -> str:
    return str(m.path.relative_to(root)) if root in m.path.parents else str(m.path)


def check_split(
    mems: list[Memory], reads: Counter, root, superseded: frozenset = frozenset()
) -> list[Finding]:
    """Rank oversized territory files by size x (1 + accretion markers) x (1 + reads).
    Only live memories (`is_live`): a superseded or record file is never split. A file held
    by `splittable: no until N KB` is skipped while it stays under N KB."""
    terr = [
        m
        for m in mems
        if m.scope == "store" and m.container != "standing" and is_live(m, superseded)
    ]
    legacy = legacy_declines(Path(root)) if root else {}
    out = []
    accreted = [m for m in terr if ACCRETION_RE.search(m.raw) and not no_split(m.meta)]
    if accreted:
        out.append(
            Finding(
                INFO,
                "accretion",
                str(root),
                f"{len(accreted)} of {len(terr)} territory files carry accretion "
                "markers (read bottom-up, history below, CORRECTION, SUPERSEDED): "
                "mutable files acting as logs. Split into state + records when "
                "next touched (direction §15 Phase 3).",
            )
        )
    big, held = [], []
    for m in terr:
        size = len(m.raw.encode())
        if size <= SPLIT_BYTES:
            continue
        rel, ns = _rel(m, root), no_split(m.meta)
        if ns and ns.ceiling_kb and size <= ns.ceiling_kb * 1024:
            held.append(size)
            continue
        if ns is None and rel in legacy:
            reason = legacy[rel] or "<the user's reason>"
            out.append(
                Finding(
                    WARN,
                    "split-decline-legacy",
                    str(m.path),
                    f"{size / 1024:.1f} KB, declined in RETRO.md, which no longer holds "
                    "split declines. Move it onto the file: "
                    f"mem no-split {rel} -m {shlex.quote(reason)}",
                )
            )
            continue
        markers, n_reads = len(ACCRETION_RE.findall(m.raw)), reads.get(rel, 0)
        big.append((size * (1 + markers) * (1 + n_reads), m, size, markers, n_reads, ns))
    big.sort(key=lambda x: -x[0])
    for rank, (_, m, size, markers, n_reads, ns) in enumerate(big, 1):
        if ns and ns.ceiling_kb:
            why = (
                f" Grew past the {ns.ceiling_kb} KB ceiling the user set when they declined a "
                f"split: {ns.reason!r}. Ask again; if it still holds, `mem no-split` "
                "raises the ceiling."
            )
        elif ns:
            why = (
                " `splittable: no` has no ceiling, so it is not honoured: ask the user, then "
                "`mem no-split` writes it with one."
            )
        else:
            why = " Why is it this big, and should it be separate memories?"
        out.append(
            Finding(
                WARN,
                "split-candidate",
                str(m.path),
                f"#{rank} of {len(big)}: {size / 1024:.1f} KB (~{size // 4:,} tokens), "
                f"{markers} accretion marker(s), read {n_reads}x in events.{why}",
            )
        )
    if held:
        out.append(
            Finding(
                INFO,
                "split-declined",
                str(root),
                f"{len(held)} file(s) over {SPLIT_BYTES // 1024} KB "
                f"({sum(held) / 1024:.0f} KB together) are under the ceiling of their "
                "`splittable: no`. They come back if they grow past it.",
            )
        )
    return out
