"""The always-loaded layer, measured as the SessionStart hook renders it, and the hook's own
output measured against the harness limit that once kept the layer out of context."""
from __future__ import annotations

from pathlib import Path

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.hooks import session_start
from claude_hybrid_memory.store import Memory, est_tokens

STANDING_CAP = 20

# The real admission gate on the always-loaded layer is STANDING_CAP -- a count, because a
# size cap gets raised the first time it trips and then means nothing. This warn is the
# secondary signal, and it is anchored to MAX_CHARS, past which session_start.py degrades
# the layer it renders into ALWAYS.md. Warning at ~83% of that says "you are approaching
# real content loss", which stays actionable as the 13 un-migrated territories add their
# EXPORTS to ROUTER.md.
# Raised from a flat 4000 on 2026-09-11, with Matt's sign-off, for exactly that reason.
ALWAYS_LOADED_TOKEN_WARN = int(session_start.MAX_CHARS / 4 * 0.83)  # 6640
# And the cliff itself. Past MAX_CHARS the hook is ALREADY dropping content, so this is not a
# warning about the future -- it is a report of loss that has happened in every session since
# the layer crossed it. A budget whose signal does not change when the thing it guards starts
# failing is the same false-reassurance this spec refuses from `last_verified`: the layer sat
# ~19% past this line for roughly three weeks while the report still read as a soft warn, and
# what was being dropped was the tail of ROUTER.md -- the exports, i.e. the gates.
ALWAYS_LOADED_TOKEN_CLIFF = session_start.MAX_CHARS // 4  # 8000


def check_budget(root: Path, mems: list[Memory]) -> list[Finding]:
    """Measure what the SessionStart hook actually injects, not what is on disk.

    `session_start.py` renders a standing directive as `## <description>` plus its body and
    throws the rest of the frontmatter away, because that layer is injected into every
    session and paying tokens for bookkeeping there is not worth it. Counting the raw files
    therefore over-reports the real context cost by the size of 11 frontmatter blocks -- a
    budget that does not measure the thing being budgeted produces exactly the kind of false
    signal `format-spec.md` refuses to accept from `last_verified`. So reuse the hook's own
    renderer; if the two ever disagree, this number is the one that is wrong.
    """
    out = []
    always = []
    # Must match session_start.py's own set, or the budget measures the wrong layer. GATES.md
    # joined it on 2026-10-02 and was briefly missing here, which under-reported by ~1k chars.
    for rel in ("MACHINE.md", "GATES.md", "ROUTER.md"):
        p = root / rel
        if p.is_file():
            always.append((rel, p.read_text(encoding="utf-8", errors="replace")))
    sdir = root / "standing"
    standing_files = sorted(sdir.glob("*.md")) if sdir.is_dir() else []
    for p in standing_files:
        always.append((f"standing/{p.name}", session_start.directive_text(p)))
    # The hook's own framing: the STANDING DIRECTIVES header, a `---` rule between each
    # directive, and the MEMORY STATUS block it appends.
    framing = 48 + max(0, len(standing_files) - 1) * 9 + 260
    total = sum(est_tokens(t) for _, t in always) + est_tokens("x" * framing)
    if always:
        out.append(Finding(INFO, "budget", str(root),
                           f"always-loaded layer: {len(always)} files, ~{total} est. tokens "
                           "as injected (hook-rendered, frontmatter excluded)"))
    if total > ALWAYS_LOADED_TOKEN_CLIFF:
        lost = total - ALWAYS_LOADED_TOKEN_CLIFF
        out.append(Finding(ERROR, "budget-truncating", str(root),
                           f"~{total} est. tokens EXCEEDS MAX_CHARS "
                           f"({ALWAYS_LOADED_TOKEN_CLIFF} tok): "
                           f"the SessionStart hook is dropping ~{lost} tok of real content every "
                           "session, from the END of the injected order. Run "
                           "`mem budget --json` for the per-file breakdown and see "
                           "what falls off with `mem hook session-start`'s own ordering."))
    elif total > ALWAYS_LOADED_TOKEN_WARN:
        out.append(Finding(WARN, "budget-high", str(root),
                           f"~{total} est. tokens exceeds the {ALWAYS_LOADED_TOKEN_WARN} "
                           "soft warn"))
    out += check_delivery(root)
    if len(standing_files) > STANDING_CAP:
        out.append(Finding(ERROR, "standing-cap", str(sdir),
                           f"{len(standing_files)} standing files exceeds the hard cap of "
                           f"{STANDING_CAP}; "
                           "evict or merge one before adding another"))
    return out


def check_delivery(root: Path, claude_md: Path | None = None) -> list[Finding]:
    """Whether the layer actually reaches a session, which the token counts above cannot say.

    Those passed at ~6,200 tokens for three weeks while every session got a 2 KB preview of
    the hook's output (session_start.py's docstring has the story). So: the CLAUDE.md import
    must be there, and the hook's own output must fit under the harness's persist threshold.
    It is measured from a directory that maps to no territory, the longest status it prints.
    """
    if not root.is_dir():
        return []
    claude_md = claude_md or session_start.CLAUDE_MD
    out = []
    want = session_start.layer(root)
    if want and not session_start.imported(root, claude_md):
        out.append(Finding(ERROR, "budget-not-imported", str(claude_md),
                           f"does not import the always-loaded layer, so no session sees "
                           f"GATES, standing or the router; add "
                           f"`{session_start.import_line(root)}` on a line of its own "
                           "(docs/setup.md step 3d)"))
    if want and session_start.read(root / session_start.ALWAYS) + "\n" != want:
        # measured on the layer as it will be, so a stale file does not count as the status
        # line `output` would add, and nothing is written here
        out.append(Finding(WARN, "budget-always-stale", str(root / session_start.ALWAYS),
                           "out of date with its sources; `mem render` rewrites it"))
    status = session_start.output_size(root, Path("/"), claude_md)
    if status > session_start.HOOK_OUTPUT_LIMIT:
        out.append(Finding(ERROR, "budget-hook-output", str(root),
                           f"the SessionStart hook prints {status:,} chars, past the "
                           f"harness's {session_start.HOOK_OUTPUT_LIMIT:,}: the model will "
                           "get a 2 KB preview and the rest goes to a file it never reads"))
    return out
