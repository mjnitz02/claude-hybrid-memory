"""SessionStart hook: keep the always-loaded memory layer current, and report status.

Four jobs, per docs/design.md:
  1. render MACHINE.md + GATES.md + standing/ + ROUTER.md into ALWAYS.md, which
     ~/.claude/CLAUDE.md imports -- that import, not this hook, is what puts it in context
  2. name the territory for the current directory, loudly when nothing maps
  3. say when the retrospective is overdue
  4. degrade in a chosen order when the layer does not fit, never by cutting the tail

Must never break a session: any failure prints nothing and exits 0. A machine with no
store is a normal state, not an error.

Why the layer is not injected from here any more (2026-10-23). Claude Code persists any one
hook's `additionalContext` longer than 10,000 chars to a file under tool-results/ and hands
the model a 2 KB preview instead (2.1.309: `yhe()`, `threshold = bri = 1e4`). The layer
was 19.5-24.8 KB in every session since 2026-10-01, so every session got MACHINE.md's first
2 KB and nothing after: no gates, no standing directives, no router. `mem budget` passed the
whole time, because MAX_CHARS below was believed to be "not a platform limit" and nothing
measured the real one. CLAUDE.md imports load a file whole (the harness's cap there is
4 MB), so the layer goes that way and this hook's output is a few hundred chars of status,
checked against HOOK_OUTPUT_LIMIT by `mem budget`. What this hook says comes FIRST in that
small output, so even a preview would carry it.

On (4), which is the hard-won part. This used to assemble MACHINE -> standing -> ROUTER
and then `text[:MAX_CHARS]`. That is the worst possible policy, and on 2026-10-02 it was
caught doing exactly what it implies: the layer had been ~19% over MAX_CHARS for weeks, so
every session silently lost the END of ROUTER.md -- which is where the exports live, i.e.
the gates. "Never write to the home server" and "never commit a template with live secrets"
were being dropped to make room for a CI punch list, mid-word, with only a marker at the
bottom to say so.

So the order of sacrifice is now explicit and runs opposite to importance:
  - MACHINE.md and GATES.md are NEVER degraded. If irreversible-harm rules cannot be
    injected, nothing else here is worth protecting.
  - standing/ bodies degrade to their descriptions, which is graceful because a
    description is written to carry the conclusion (format-spec.md).
  - the ROUTER map is cut LAST, and only its trailing territory entries, with an explicit
    note naming what was dropped. A missing map entry costs a lookup; a missing gate costs
    a mistake.
Nothing is ever cut mid-word again, and every degradation announces itself in-band.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from claude_hybrid_memory.harness import silo_name

STORE = Path(os.environ.get("CLAUDE_MEMORY_STORE", Path.home() / ".claude" / "memory"))
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects"))
RETRO_DUE_DAYS = 30

# The ceiling on the always-loaded layer (ALWAYS.md). Not a platform limit -- that is
# HOOK_OUTPUT_LIMIT, below, and it applies to what this hook prints, not to ALWAYS.md,
# which reaches context through a CLAUDE.md import. This is the store's own guard against
# the layer becoming the undifferentiated dump the store exists to escape.
#
# (Until 2026-10-23 this comment said "nothing in the harness enforces it", and the layer
# was injected from this hook. Something did: see HOOK_OUTPUT_LIMIT.)
#
# 24,000 (2026-09-04) was an unexamined guess: `git log -S` puts it in the first commit of
# this tool with no rationale recorded anywhere, chosen when zero territories had been
# migrated. Raised to 32,000 on 2026-10-02 with Matt's sign-off, and the rationale is
# recorded here because the previous number's absence of one is half of why the layer could
# sit 19% past it for three weeks:
#
#   - The content is now all load-bearing. The restructure that preceded this raise removed
#     a CI punch list from `standing/` (23% of the whole layer) and deleted a duplicated
#     exports block from ROUTER.md that `mem.py`'s own model never required. There is no
#     slack left to reclaim; the next cut would be evidence, not fat.
#   - `ROUTER.md` grows with the store BY DESIGN -- ~250 chars per territory, with 10 of 18
#     still unmigrated. A ceiling that forces a trim every third migration is a ceiling that
#     makes the system worse as it works.
#   - Exceeding it is no longer dangerous. Degradation is ordered, bounded and announced
#     (see the module docstring), so this number now sets *quality*, not safety. That is
#     exactly the change that makes raising it defensible when it was not before.
#
# What must NOT move is mem.py's STANDING_CAP -- the file count on `standing/`, which is the
# real admission gate and is still at its original 20. This number and that one are
# different things; conflating them is what made "raise the budget" feel like cheating.
MAX_CHARS = 32000

# The platform limit. Claude Code 2.1.309 persists any one hook output longer than this
# (`bri=1e4`, compared against the JS string length) and the model sees a 2 KB preview.
# Re-read it from the binary after a harness upgrade; `mem budget` errors past it.
HOOK_OUTPUT_LIMIT = 10_000

ALWAYS = "ALWAYS.md"
ALWAYS_HEAD = ("<!-- Generated by `mem` from MACHINE.md, GATES.md, standing/ and ROUTER.md, "
               "and imported by ~/.claude/CLAUDE.md. Edit those, not this file. -->")
CLAUDE_MD = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "CLAUDE.md"


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def directive_text(p: Path) -> str:
    """Render a standing directive as its description plus body.

    The raw frontmatter is bookkeeping, and this layer is injected into every single
    session, so it is the one place where paying tokens for metadata is not worth it.
    """
    raw = read(p)
    if not raw.startswith("---"):
        return raw
    end = raw.find("\n---", 3)
    if end == -1:
        return raw
    fm, body = raw[3:end], raw[end + 4:].strip()
    m = re.search(r"^description:\s*(.+)$", fm, re.M)
    desc = m.group(1).strip().strip("\"'") if m else p.stem
    return f"## {desc}\n\n{body}" if body else f"## {desc}"


def territory_for(cwd: Path, store: Path) -> tuple[str | None, list[str]]:
    """Find which territory this directory is pointed at, and list all territories."""
    tdir = store / "territories"
    all_t: list[str] = []
    if tdir.is_dir():
        all_t = sorted(str(m.parent.relative_to(tdir)) for m in tdir.rglob("MEMORY.md"))
    # walk up looking for a git root, then check that silo's memory symlink
    probe = cwd
    for _ in range(40):
        if (probe / ".git").exists():
            break
        if probe.parent == probe:
            probe = cwd
            break
        probe = probe.parent
    # The silo is named the harness's way (claude_hybrid_memory.harness). Encoding only "/ . _"
    # here once meant paths with "~", "@" or a space never found their territory.
    tdir_r = tdir.resolve()
    for cand in (probe, cwd):
        link = PROJECTS / silo_name(str(cand)) / "memory"
        try:
            if link.is_symlink():
                target = Path(os.path.realpath(link))
                if tdir_r == target.parent or tdir_r in target.parents:
                    return str(target.relative_to(tdir_r)), all_t
        except (OSError, ValueError):
            continue
    return None, all_t


def retro_overdue(router: str) -> int | None:
    m = re.search(r"^last_retrospective:\s*(\d{4}-\d{2}-\d{2})", router, re.M)
    if not m:
        return None
    try:
        last = dt.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    age = (dt.date.today() - last).days
    return age if age > RETRO_DUE_DAYS else None


def directive_desc(p: Path) -> str:
    """Just the `## description` line -- the degraded form of a standing directive.

    Safe to fall back to because format-spec.md requires a description to carry the
    CONCLUSION rather than the subject, so the directive still fires; only its reasoning
    and its `How to apply` list are lost.
    """
    full = directive_text(p)
    return full.split("\n\n", 1)[0] if full else ""


def fit(protected: list[str], standing: list[Path], router: str,
        status: str) -> tuple[str, list[str]]:
    """Assemble the layer under MAX_CHARS, degrading in the documented order.

    Returns the text plus a list of human-readable notes about what was degraded, so a
    session is never quietly handed less than it thinks it has.
    """
    notes: list[str] = []

    def build(directives: list[str], router_text: str) -> str:
        parts = list(protected)
        if directives:
            parts.append("# STANDING DIRECTIVES (always in force)\n\n"
                         + "\n\n---\n\n".join(directives))
        if router_text:
            parts.append(router_text)
        if status:
            parts.append(status)
        return "\n\n".join(parts).strip()

    rendered = {p: directive_text(p) for p in standing}
    order = [p for p in standing if rendered[p]]
    text = build([rendered[p] for p in order], router)
    if len(text) <= MAX_CHARS:
        return text, notes

    # Degradation 1: shorten standing directives to their descriptions, BIGGEST FIRST and
    # only as many as needed. Shortening all of them to save 4k chars would throw away 17k
    # -- the first version of this did exactly that. In practice one oversized directive is
    # usually the whole overage, so this costs one directive's reasoning instead of all of
    # them, and the note names which.
    shortened: list[str] = []
    for victim in sorted(order, key=lambda q: -len(rendered[q])):
        rendered[victim] = directive_desc(victim)
        shortened.append(victim.stem)
        text = build([rendered[p] for p in order], router)
        if len(text) <= MAX_CHARS:
            break
    notes.append("**Shown as a one-line conclusion only, to fit the context budget: "
                 + ", ".join(f"`{s}`" for s in shortened)
                 + ".** Each still applies in full — read it in `~/.claude/memory/standing/` "
                 "before acting against it or arguing with it.")
    if len(text) <= MAX_CHARS:
        return text, notes
    short = [rendered[p] for p in order]

    # Degradation 2: drop trailing ROUTER map entries, on whole-section boundaries, and
    # say which. The gates and MACHINE are never touched.
    overflow = len(text) - MAX_CHARS
    sections = re.split(r"(?m)^(?=## )", router)
    dropped: list[str] = []
    while overflow > 0 and len(sections) > 1:
        gone = sections.pop()
        dropped.append((gone.splitlines() or ["?"])[0].lstrip("# ").strip())
        overflow -= len(gone)
    text = build(short, "".join(sections).rstrip())
    notes.append("**The router map is truncated.** These sections were NOT injected: "
                 + ", ".join(dropped) + ". Read `~/.claude/memory/ROUTER.md` directly.")
    return text, notes


def import_line(store: Path) -> str:
    """The CLAUDE.md line that loads ALWAYS.md, home-relative where it can be."""
    p = store / ALWAYS
    try:
        return "@~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return f"@{p}"


def imported(store: Path, claude_md: Path) -> bool:
    """Whether CLAUDE.md imports this store's ALWAYS.md, on a line of its own."""
    want = os.path.realpath(store / ALWAYS)
    return any(os.path.realpath(os.path.expanduser(ln.strip()[1:])) == want
               for ln in read(claude_md).splitlines() if ln.strip().startswith("@"))


def layer(store: Path) -> str:
    """The always-loaded layer, degraded under MAX_CHARS, as ALWAYS.md holds it."""
    # PROTECTED: never degraded, never truncated, and emitted first so that no later
    # growth anywhere in the layer can push them out. GATES.md goes directly after
    # MACHINE.md because an irreversible-harm rule is the one thing whose absence is
    # unrecoverable -- the session cannot know to go and look for it.
    protected = [t for t in (read(store / "MACHINE.md"), read(store / "GATES.md")) if t]
    sdir = store / "standing"
    standing = sorted(sdir.glob("*.md")) if sdir.is_dir() else []
    router = read(store / "ROUTER.md")
    if not (protected or standing or router):
        return ""
    # Degrading may itself produce notes that belong in the layer, so it is built twice:
    # once to measure, once for real.
    text, degraded = fit(protected, standing, router, "")
    if degraded:
        degraded.append("Run `mem budget` -- the always-loaded layer is over MAX_CHARS and "
                        "this is a real loss, not a warning.")
        text, _ = fit(protected, standing, router,
                      "# LAYER NOTES\n\n" + "\n\n".join(f"- {n}" for n in degraded))
    return f"{ALWAYS_HEAD}\n\n{text}\n"


def write_always(store: Path) -> bool:
    """Bring ALWAYS.md up to date; True when it changed."""
    new = layer(store)
    p = store / ALWAYS
    if not new or read(p) + "\n" == new:
        return False
    tmp = p.with_name(ALWAYS + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, p)
    return True


def output_size(store: Path, cwd: Path, claude_md: Path = CLAUDE_MD) -> int:
    """len(output(...)) at its longest, without writing ALWAYS.md."""
    return len(output(store, cwd, claude_md, write=False))


def output(store: Path, cwd: Path, claude_md: Path = CLAUDE_MD, write: bool = True) -> str:
    """What the hook injects: status only, which must stay under HOOK_OUTPUT_LIMIT.

    With `write` False nothing is written and the stale note is counted as if it fired."""
    notes = []
    stale = write_always(store) if write else True
    always = store / ALWAYS
    if always.is_file() and not imported(store, claude_md):
        notes.append(f"**The always-loaded layer is NOT in context.** {claude_md} does not "
                     f"import it, so GATES, the standing directives and the router were not "
                     f"loaded. Read `{always}` now, before acting, and add the line "
                     f"`{import_line(store)}` to {claude_md} (docs/setup.md step 3d).")
    elif stale:
        notes.append(f"`{always}` was out of date and has just been re-rendered, so the "
                     "copy CLAUDE.md loaded this session may be older than the store. "
                     "Re-read it before relying on GATES, standing or the router.")

    terr, all_t = territory_for(cwd, store)
    if terr and terr not in all_t:
        notes.append(f"**This directory's silo points at {terr}, which no longer exists.** "
                     f"({cwd}) No territory MEMORY.md loaded. It was probably renamed or "
                     "archived: find where in ROUTER.md, then repoint it from the repo with "
                     "`mem link --territory <new> --write`.")
    elif terr:
        notes.append(f"Territory for this directory: **{terr}**. Its MEMORY.md is "
                     "auto-loaded; read its internals on demand.")
    elif all_t:
        notes.append(f"**This directory maps to NO territory.** ({cwd}) Memory written "
                     "here will land in an unrouted per-directory silo, which is the "
                     "problem the store exists to fix. Consider pointing it at one of: "
                     + ", ".join(all_t) + " (see docs/setup.md step 5).")
    overdue = retro_overdue(read(store / "ROUTER.md"))
    if overdue is not None:
        notes.append(f"Memory retrospective is **{overdue} days** old "
                     f"(cadence {RETRO_DUE_DAYS}d). Run `/memory-retro` when there is "
                     "a natural pause.")
    return ("# MEMORY STATUS\n\n" + "\n\n".join(f"- {n}" for n in notes)) if notes else ""


def main() -> int:
    if not STORE.is_dir():
        return 0
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    text = output(STORE, cwd)
    if not text:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never break a session over memory loading.
        sys.exit(0)
