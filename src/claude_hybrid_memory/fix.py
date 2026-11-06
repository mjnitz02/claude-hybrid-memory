"""`mem fix`: autofix what is mechanical, report what is not."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.spec import OBSOLETE_FIELDS, STATUSES
from claude_hybrid_memory.store import Memory, _Loader, parse_frontmatter

_FM_LINE = re.compile(r"^(\s*)([A-Za-z_][\w.-]*)(\s*:\s+)(\S.*?)\s*$")


def desired_slug(stem: str) -> str:
    w = re.sub(r"[_\s]+", "-", stem).lower()
    w = re.sub(r"[^a-z0-9-]", "", w)
    w = re.sub(r"-{2,}", "-", w).strip("-")
    return w or stem.lower()


def _needs_quote(v: str) -> bool:
    if v[0] in "\"'":
        return False
    return ": " in v or " #" in v or v.endswith(":") or v[0] in "*&!|>%@`[{,?-#"


def quote_frontmatter(text: str) -> tuple[str, list[str]] | None:
    """Double-quote each plain scalar YAML misreads (`frontmatter-not-yaml`).

    Quotes the raw text after `key: `, not the lenient parser's value, which strips quote
    characters. Returns None unless strict YAML then reads every quoted value back verbatim.
    """
    end = text.find("\n---", 3)
    lines, quoted, parent = text[3:end].split("\n"), {}, None
    for i, ln in enumerate(lines):
        m = _FM_LINE.match(ln)
        if not m:
            if re.match(r"^[A-Za-z_][\w.-]*\s*:\s*$", ln):
                parent = ln.split(":")[0].strip()
            continue
        indent, key, sep, val = m.groups()
        if not indent:
            parent = None
        if _needs_quote(val):
            quoted[(parent if indent else None, key)] = val
            esc = val.replace("\\", "\\\\").replace('"', '\\"')
            lines[i] = f'{indent}{key}{sep}"{esc}"'
    if not quoted:
        return None
    block = "\n".join(lines)
    try:
        meta = yaml.load(block, _Loader)
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    for (par, key), val in quoted.items():
        got = (meta.get(par) or {}).get(key) if par else meta.get(key)
        if got != val:
            return None
    new = text[:3] + block + text[end:]
    if parse_frontmatter(new)[2]:
        return None
    return new, sorted(k for _, k in quoted)


# What the harness's auto-memory recipe nests under `metadata:`, and the store never reads.
# `modified` is kept (hoisted) only where there is no last_verified, since backfill-verified
# reads it as the date a file was written (verified.written_date).
HARNESS_FIELDS = ("node_type", "type", "originSessionId", "modified")


def flatten_harness(text: str, router: bool = False) -> tuple[str, list[str]] | None:
    """Fold a harness `metadata:` block into flat frontmatter: drop HARNESS_FIELDS, hoist
    everything else one level (a key already at the top level wins, as the loader's hoist
    already decided), and drop the harness's empty `name: ""`. As text, so comments and flow
    style survive. None when there is no block, or the result would not read back with
    every kept value unchanged. A router (MEMORY.md) has no last_verified to stand in for,
    so it never keeps `modified`."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    lines = text[4:end].split("\n") if text.startswith("---\n") else None
    if lines is None:
        return None
    try:
        i = next(n for n, ln in enumerate(lines) if re.match(r"^metadata:\s*$", ln))
    except StopIteration:
        return None
    j = i + 1
    while j < len(lines) and (lines[j][:1] in (" ", "\t") or not lines[j].strip()):
        j += 1
    block, top = lines[i + 1 : j], lines[:i] + lines[j:]
    top_keys = {m.group(1) for ln in top if (m := re.match(r"^([A-Za-z_][\w.-]*)\s*:", ln))}
    has_lv = (
        router
        or "last_verified" in top_keys
        or any(re.match(r"^\s+last_verified\s*:", ln) for ln in block)
    )
    base = min((len(ln) - len(ln.lstrip()) for ln in block if ln.strip()), default=0)
    kept, actions, skip = [], [], False
    for ln in block:
        if not ln.strip():
            continue
        depth = len(ln) - len(ln.lstrip())
        if depth == base:
            key = ln.strip().split(":", 1)[0].strip()
            drop = (
                key in HARNESS_FIELDS and not (key == "modified" and not has_lv)
            ) or key in top_keys
            skip = drop
            if drop:
                actions.append(
                    f"dropped {key}" + (" (already at top level)" if key in top_keys else "")
                )
                continue
            actions.append(f"hoisted {key}")
        elif skip:
            continue
        kept.append(ln[base:])
    empty_name = [n for n, ln in enumerate(top) if re.match(r'^name:\s*(""|\'\')?\s*$', ln)]
    if empty_name and not any(re.match(r"^name\s*:", ln) for ln in kept):
        actions.append('dropped name: ""')
    for n in reversed(empty_name):
        top.pop(n)
    new_lines = top[:i] + kept + top[i:]
    new = "---\n" + "\n".join(new_lines) + text[end:]
    before, _, _ = parse_frontmatter(text)
    after, _, problems = parse_frontmatter(new)
    if problems or "metadata" in after:
        return None
    for k, v in after.items():
        if k in before and before[k] != v and not (k == "name" and not before[k]):
            return None
    for k, v in before.items():
        if k not in ("metadata", "name", *HARNESS_FIELDS) and after.get(k) != v:
            return None
    return new, actions


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
            out.append(
                Finding(
                    ERROR,
                    "fix-collision",
                    str(m.path),
                    f"renaming to {want}.md would collide with {taken[key].name} "
                    f"in {m.container}; resolve by hand",
                )
            )
            continue
        taken[key] = m.path
        plan[m.path] = (want, m.path.with_name(want + ".md"))

    renames = {
        m.stem: plan[m.path][0] for m in mems if m.path in plan and plan[m.path][0] != m.stem
    }

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

        if m.fm_problems:
            q = quote_frontmatter(text)
            if q:
                text = q[0]
                actions.append(f"quoted {', '.join(q[1])} (frontmatter-not-yaml)")
            else:
                out.append(
                    Finding(
                        WARN,
                        "fix-frontmatter-skip",
                        str(m.path),
                        "frontmatter is not valid YAML and quoting would not read "
                        "back verbatim; fix by hand",
                    )
                )

        flat = flatten_harness(text)
        if flat:
            text = flat[0]
            actions.append("flattened harness metadata: (" + ", ".join(flat[1]) + ")")

        if not m.name:
            if m.meta and re.search(r"^name\s*:", text[: text.find("\n---", 3)], re.M):
                text = re.sub(r"^(name\s*:).*$", rf"\g<1> {want}", text, count=1, flags=re.M)
            elif m.meta:
                text = re.sub(r"^---\n", f"---\nname: {want}\n", text, count=1)
            else:
                text = f"---\nname: {want}\nkind: territory\n---\n" + text
            actions.append(f"insert name: {want}")
        elif m.name != want:
            text = re.sub(
                r"^(\s*name:\s*).*$", lambda mo, w=want: mo.group(1) + w, text, count=1, flags=re.M
            )
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

        old = [k for k in OBSOLETE_FIELDS if k in m.meta]
        if old and text.startswith("---"):
            end = text.find("\n---", 3)
            # indented too: the loader hoists keys nested under a harness `metadata:` block
            fm = re.sub(rf"^[ \t]*(?:{'|'.join(old)})\s*:.*\n", "", text[: end + 1], flags=re.M)
            text = fm + text[end + 1 :]
            actions.append(f"removed {', '.join(old)} (obsolete-field)")

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

    # 3. routers reference files by path, so they must move too; and a router's frontmatter
    # gets the same flattening (cards/archive/MEMORY.md had a harness block, 2026-11-04)
    for r in routers.values():
        text = rewrite_links(r.raw)
        what = ["updated renamed file references"] if text != r.raw else []
        flat = flatten_harness(text, router=True)
        if flat:
            text = flat[0]
            what.append("flattened harness metadata: (" + ", ".join(flat[1]) + ")")
        if text == r.raw:
            continue
        out.append(Finding(INFO, "fix-router", str(r.path), "; ".join(what)))
        if write:
            r.path.write_text(text, encoding="utf-8")

    if not stamp_today:
        out.append(
            Finding(
                INFO,
                "fix-no-stamp",
                "-",
                "last_verified NOT stamped. mtime is not evidence of verification "
                "(a copy or checkout resets it), and a wrong date is worse than a "
                "missing one. Pass --stamp-today only when the claims were actually "
                "checked.",
            )
        )
    if out and not write:
        out.append(Finding(INFO, "fix-dry-run", "-", "dry run; pass --write to apply"))
    return out
