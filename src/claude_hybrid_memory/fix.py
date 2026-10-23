"""`mem fix`: autofix what is mechanical, report what is not."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from claude_hybrid_memory.findings import ERROR, INFO, Finding
from claude_hybrid_memory.spec import STATUSES
from claude_hybrid_memory.store import Memory


def desired_slug(stem: str) -> str:
    w = re.sub(r"[_\s]+", "-", stem).lower()
    w = re.sub(r"[^a-z0-9-]", "", w)
    w = re.sub(r"-{2,}", "-", w).strip("-")
    return w or stem.lower()


def do_fix(mems: list[Memory], routers: dict, write: bool, stamp_today: bool) -> list[Finding]:
    """Plan every change first, then apply once per file.

    Deliberately single-pass on write: an earlier two-pass version rewrote inbound links
    from each file's ORIGINAL text, silently clobbering the frontmatter edits made in the
    first pass. Plan-then-apply makes that class of bug impossible.
    """
    out: list[Finding] = []
    today = dt.date.today().isoformat()

    # 1. plan slugs, and detect targets that would collide inside one container
    plan: dict[Path, tuple[str, Path]] = {}
    taken: dict[tuple[str, str], Path] = {}
    for m in mems:
        want = desired_slug(m.stem)
        key = (m.container, want)
        if key in taken and taken[key] != m.path:
            out.append(Finding(ERROR, "fix-collision", str(m.path),
                               f"renaming to {want}.md would collide with {taken[key].name} "
                               f"in {m.container}; resolve by hand"))
            continue
        taken[key] = m.path
        plan[m.path] = (want, m.path.with_name(want + ".md"))

    renames = {m.stem: plan[m.path][0] for m in mems
               if m.path in plan and plan[m.path][0] != m.stem}

    def rewrite_links(text: str) -> str:
        for old, new in renames.items():
            text = text.replace(f"[[{old}]]", f"[[{new}]]")
            text = text.replace(f"]({old}.md)", f"]({new}.md)")
        return text

    # 2. apply, one write per file
    for m in mems:
        if m.path not in plan:
            continue
        want, target = plan[m.path]
        text, actions = m.raw, []

        if not m.name:
            if m.meta:
                text = re.sub(r"^---\n", f"---\nname: {want}\n", text, count=1)
            else:
                text = f"---\nname: {want}\nkind: territory\n---\n" + text
            actions.append(f"insert name: {want}")
        elif m.name != want:
            text = re.sub(r"^(\s*name:\s*).*$", lambda mo, w=want: mo.group(1) + w,
                          text, count=1, flags=re.M)
            actions.append(f"name: {m.name!r} -> {want}")

        if not str(m.meta.get("kind") or "").strip() and text.startswith("---"):
            text = re.sub(r"^---\n", "---\nkind: territory\n", text, count=1)
            actions.append("kind: territory (spec default)")

        # Descriptions already carry a status word by Matt's own CLAUDE.md convention
        # ("SHIPPED 2026-07-30, resume dropped, ..."). Lifting it into a field is reading
        # what is there, not guessing: volatility then derives from it.
        if not str(m.meta.get("status") or "").strip() and text.startswith("---"):
            desc = str(m.meta.get("description") or "").strip().strip("\"'")
            for st in sorted(STATUSES, key=len, reverse=True):
                if re.match(rf"^{re.escape(st)}\b", desc, re.I):
                    text = re.sub(r"^---\n", f"---\nstatus: {st}\n", text, count=1)
                    actions.append(f"status: {st} (lifted from description)")
                    break

        if stamp_today and not m.meta.get("last_verified") and text.startswith("---"):
            text = re.sub(r"^---\n", f"---\nlast_verified: {today}\n", text, count=1)
            actions.append(f"stamp last_verified: {today} (asserted now)")

        linked = rewrite_links(text)
        if linked != text:
            actions.append("rewrote inbound links")
            text = linked

        if target != m.path:
            actions.append(f"rename -> {target.name}")

        if not actions:
            continue
        out.append(Finding(INFO, "fix", str(m.path), "; ".join(actions)))
        if write:
            target.write_text(text, encoding="utf-8")
            if target != m.path:
                m.path.unlink()

    # 3. routers reference files by path, so they must move too
    for r in routers.values():
        text = rewrite_links(r.raw)
        if text == r.raw:
            continue
        out.append(Finding(INFO, "fix-router", str(r.path), "updated renamed file references"))
        if write:
            r.path.write_text(text, encoding="utf-8")

    if not stamp_today:
        out.append(Finding(INFO, "fix-no-stamp", "-",
                           "last_verified NOT stamped. mtime is not evidence of verification "
                           "(a copy or checkout resets it), and a wrong date is worse than a "
                           "missing one. Pass --stamp-today only when the claims were actually "
                           "checked."))
    if out and not write:
        out.append(Finding(INFO, "fix-dry-run", "-", "dry run; pass --write to apply"))
    return out
