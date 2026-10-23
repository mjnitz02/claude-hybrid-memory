"""Moving things around the store after they have landed.

`mem migrate` only brings legacy silos in. Once a territory exists, renaming it or moving
it to another area was a manual job, and the manual job has many places to forget: the
directory, every silo symlink pointing at it, its ROUTER.md entry, its own header, other
territories' `consumes:`/`consumed_by:`, `container/slug` refs in `supersedes:`, and the
migration plan (the refine queue finds landed files through it). Forgetting a silo is the
worst of them: the repo silently loads no memory.

Moving single memories between territories is smaller but has its own traps: both
indexes, and `container/slug` refs in `supersedes:`. A moved file that landed through
`mem migrate` drops out of the refine queue's summary items, since the plan still says
where it landed; its audit items follow it.

Each move is one store commit, with a checkpoint commit before it. Prose that names the
old path is reported, never rewritten: whether a sentence should follow the move is a
judgment call. RETRO.md and archive/ are history and left alone.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from claude_hybrid_memory import storegit
from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.migrate import plan as P

SKIP_PROSE = ("RETRO.md", "ALWAYS.md")


def _token(name: str) -> re.Pattern:
    """`name` as a whole territory path, also inside `territories/<name>/x.md`, but not
    as a prefix of `name-two`."""
    return re.compile(rf"(?<![\w.-]){re.escape(name)}(?![\w-])")


@dataclass
class Change:
    edits: dict[Path, str] = field(default_factory=dict)    # path (pre-move) -> new text
    notes: list[Finding] = field(default_factory=list)


@dataclass
class Move(Change):
    old: str = ""
    new: str = ""
    links: list[Path] = field(default_factory=list)          # silo memory symlinks to repoint
    plan: dict | None = None


@dataclass
class FileMove(Change):
    dest: str = ""
    files: list[tuple[str, Path]] = field(default_factory=list)   # (source territory, file)
    carried: list[str] = field(default_factory=list)   # hand-written index lines to carry


def _text(ch: Change, p: Path) -> str:
    """The text of `p` with this change's edits so far."""
    return ch.edits.get(p) if p in ch.edits else p.read_text(encoding="utf-8")


def _frontmatter_span(text: str) -> tuple[int, int]:
    if not text.startswith("---"):
        return 0, 0
    end = text.find("\n---", 3)
    return (0, end) if end != -1 else (0, 0)


def _own_index(mv: Move, index: Path) -> None:
    text = _text(mv, index)
    _, end = _frontmatter_span(text)
    head = re.sub(rf"(?m)^(\s*territory:\s*){re.escape(mv.old)}\s*$",
                  lambda m: m.group(1) + mv.new, text[:end])
    rest = re.sub(rf"(?m)^(#\s+){re.escape(mv.old)}\b", lambda m: m.group(1) + mv.new,
                  text[end:], count=1)
    new = head + rest
    if new != text:
        mv.edits[index] = new


def _refs(mv: Move, tdir: Path, own: Path) -> None:
    """`consumes:`/`consumed_by:` in every other index; `supersedes:` refs everywhere."""
    tok = _token(mv.old)
    sup_ref = re.compile(rf"(?<![\w.-]){re.escape(mv.old)}/")
    for p in sorted(tdir.rglob("*.md")):
        text = _text(mv, p)
        _, end = _frontmatter_span(text)
        if not end:
            continue
        lines = text[:end].split("\n")
        in_sup = False
        for i, ln in enumerate(lines):
            key = re.match(r"^\s*([\w-]+):", ln)
            if key:
                in_sup = key.group(1) == "supersedes"
            if key and key.group(1) in ("consumes", "consumed_by") and p.name == "MEMORY.md" \
                    and p != own:
                lines[i] = tok.sub(mv.new, ln)
            elif in_sup:
                lines[i] = sup_ref.sub(mv.new + "/", ln)
        new = "\n".join(lines) + text[end:]
        if new != text:
            mv.edits[p] = new


def _router(mv: Move, router: Path) -> None:
    from claude_hybrid_memory.render import ROUTER_ENTRY_RE

    if not router.is_file():
        return
    text = _text(mv, router)
    lines = text.split("\n")
    at = next((i for i, ln in enumerate(lines)
               if (m := ROUTER_ENTRY_RE.match(ln))
               and mv.old in re.split(r",\s*", m.group("names"))), None)
    if at is None:
        mv.notes.append(Finding(WARN, "mv-no-router-entry", str(router),
                                f"no entry names {mv.old}; add one for {mv.new} by hand"))
        return
    end = at + 1
    while end < len(lines) and lines[end].startswith((" ", "\t")):
        end += 1
    block = lines[at:end]
    block[0] = _token(mv.old).sub(mv.new, block[0], count=1)
    grouped = len(re.split(r",\s*", ROUTER_ENTRY_RE.match(lines[at]).group("names"))) > 1
    area_old, area_new = mv.old.split("/", 1)[0], mv.new.split("/", 1)[0]
    if area_old == area_new or grouped:
        lines[at:end] = block
        if area_old != area_new:
            mv.notes.append(Finding(WARN, "mv-router-grouped", str(router),
                                    f"{mv.new} shares an entry under ## {area_old}; renamed "
                                    f"in place, move it under ## {area_new} by hand"))
    else:
        del lines[at:end]
        if not any(ROUTER_ENTRY_RE.match(ln) and ln[2:].startswith(area_old + "/")
                   for ln in lines):
            mv.notes.append(Finding(WARN, "mv-router-area-empty", str(router),
                                    f"## {area_old} has no entries left; remove the section "
                                    "if the area is done"))
        lines = _insert_under(lines, area_new, block, mv, router)
    mv.edits[router] = "\n".join(lines)


def _insert_under(lines: list[str], area: str, block: list[str], mv: Move,
                  router: Path) -> list[str]:
    """`block` after the last entry of `## <area>`, or in a new section after the last one
    that holds entries (ROUTER.md can end in sections that are not areas, like exports)."""
    from claude_hybrid_memory.render import ROUTER_ENTRY_RE

    head = next((i for i, ln in enumerate(lines) if re.match(rf"^## {re.escape(area)}\b", ln)),
                None)
    if head is None:
        mv.notes.append(Finding(WARN, "mv-router-new-area", str(router),
                                f"no ## {area} section; added one after the last area, give "
                                "it a one-line description"))
        last = max((i for i, ln in enumerate(lines) if ROUTER_ENTRY_RE.match(ln)), default=None)
        at = len(lines) if last is None else next(
            (i for i in range(last + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while at > 0 and not lines[at - 1].strip():
            at -= 1
        return lines[:at] + ["", f"## {area}", *block] + lines[at:]
    nxt = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")),
               len(lines))
    last = nxt
    while last > head + 1 and not lines[last - 1].strip():
        last -= 1
    return lines[:last] + block + lines[last:]


def _plan(mv: Move, root: Path) -> None:
    """Rewrite the migration plan's territory names. An approval that covered the plan as it
    was still covers it: a rename changes no decision, so it is re-stamped, not voided."""
    plan = P.load(root)
    if not plan:
        return
    was_approved = bool(plan.get("approved")) and \
        plan["approved"].get("decisions") == P.decisions(plan)
    hit = False
    for s in plan.get("silos", []):
        if s.get("territory") == mv.old:
            s["territory"], hit = mv.new, True
        for f in s.get("files", []):
            if f.get("to") == mv.old:
                f["to"], hit = mv.new, True
    if not hit:
        return
    if was_approved:
        plan["approved"]["decisions"] = P.decisions(plan)
    mv.plan = plan


def _silos(mv: Move, legacy: Path, old_dir: Path) -> None:
    if not legacy.is_dir():
        return
    target = old_dir.resolve()
    for silo in sorted(legacy.iterdir()):
        md = silo / "memory"
        if md.is_symlink() and Path(os.path.realpath(md)) == target:
            mv.links.append(md)


def _prose(ch: Change, root: Path, tok: re.Pattern) -> None:
    """Every remaining mention of the old path, after this change's edits."""
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if rel.parts[0] in ("archive", "events", ".cache", ".git") or rel.name in SKIP_PROSE:
            continue
        for n, ln in enumerate(_text(ch, p).split("\n"), 1):
            if tok.search(ln):
                ch.notes.append(Finding(WARN, "mv-prose", f"{rel}:{n}", ln.strip()[:120]))


def plan_territory(root: Path, legacy: Path, old: str, new: str) -> Move | list[Finding]:
    """Everything a move would change, computed without writing; or why it can't happen."""
    tdir = root / "territories"
    errs = []
    if not (tdir / old / "MEMORY.md").is_file():
        errs.append(Finding(ERROR, "mv-no-territory", old, "no such territory"))
    if not P.TERRITORY_RE.match(new):
        errs.append(Finding(ERROR, "mv-bad-name", new, "not a lowercase area/name"))
    elif (tdir / new).exists():
        errs.append(Finding(ERROR, "mv-target-exists", new,
                            "already exists; merging territories is a different operation"))
    if errs:
        return errs
    mv = Move(old=old, new=new)
    _own_index(mv, tdir / old / "MEMORY.md")
    _refs(mv, tdir, tdir / old / "MEMORY.md")
    _router(mv, root / "ROUTER.md")
    _plan(mv, root)
    _silos(mv, legacy, tdir / old)
    _prose(mv, root, _token(old))
    return mv


def describe(root: Path, mv: Move, done: bool) -> list[Finding]:
    verb = "moved" if done else "would move"
    out = [Finding(INFO, "mv-dir", f"territories/{mv.old}", f"{verb} to territories/{mv.new}")]
    out += [Finding(INFO, "mv-edit", str(p.relative_to(root)).replace(
        f"territories/{mv.old}/", f"territories/{mv.new}/"), "rewritten" if done else
        "would rewrite") for p in sorted(mv.edits)]
    if mv.plan:
        out.append(Finding(INFO, "mv-edit", str(P.path(root).relative_to(root)),
                           "rewritten" if done else "would rewrite"))
    out += [Finding(INFO, "mv-silo", md.parent.name,
                    f"{'repointed' if done else 'would repoint'} -> {mv.new}")
            for md in mv.links]
    return out + mv.notes


def apply_territory(root: Path, legacy: Path, mv: Move) -> list[Finding]:
    """Write the move: checkpoint commit, the changes, re-render, commit. Audit errors the
    move introduced are reported with the move that reverses it (a git revert would leave
    the silo symlinks, which live outside the store, pointing at nothing)."""
    tdir = root / "territories"

    def write() -> None:
        old_dir, new_dir = tdir / mv.old, tdir / mv.new
        for p, text in mv.edits.items():
            p.write_text(text, encoding="utf-8")
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        old_dir.rename(new_dir)
        if old_dir.parent != tdir and not any(old_dir.parent.iterdir()):
            old_dir.parent.rmdir()
        for md in mv.links:
            md.unlink()
            md.symlink_to(new_dir)
        if mv.plan:
            P.write(root, mv.plan)

    tok = _token(mv.old)
    return _committed(root, legacy, "mem mv-territory", f"mv-territory: {mv.old} -> {mv.new}",
                      write, lambda path: tok.sub(mv.new, path),
                      f"`mem mv-territory {mv.new} {mv.old} --write` reverses it",
                      lambda: describe(root, mv, True))


def _committed(root: Path, legacy: Path, trigger: str, subject: str, write, remap, undo: str,
               done) -> list[Finding]:
    """Checkpoint commit, `write()`, re-render, commit; then any audit error that was not
    there before. `remap` carries an old error path to where the move put it, so the same
    error under a new path is not new."""
    from claude_hybrid_memory import render
    from claude_hybrid_memory.migrate import apply

    snap = storegit.commit(root, trigger, subject=f"before {trigger}")
    if snap.status not in ("committed", "clean"):
        return [Finding(ERROR, "mv-unsafe", str(root),
                        f"safety commit {snap.status}: {snap.detail}; nothing moved")]
    before = {(code, remap(path)) for code, path in apply.errors(root, legacy)}
    write()
    render.render_all(root)
    c = storegit.commit(root, trigger, subject=subject)
    out = done()
    if c.status == "committed":
        out.append(Finding(INFO, "mv-committed", c.sha, c.detail))
    out += [Finding(ERROR, "mv-new-error", path, f"{code} appeared after the move; {undo}")
            for code, path in sorted(apply.errors(root, legacy) - before)]
    return out


ENTRY_LINE = r"^- \[[^\]]*\]\({}\).*$"


def _resolve(tdir: Path, spec: str) -> tuple[str, Path] | Finding:
    """`slug`, `area/name/slug` or a path to a territory memory -> (territory, file)."""
    p = Path(spec).expanduser()
    if p.suffix == ".md" and p.is_file():
        p = p.resolve()
        try:
            rel = p.relative_to(tdir.resolve())
        except ValueError:
            return Finding(ERROR, "mv-not-territory", spec,
                           "not under territories/; standing and archive moves are other "
                           "operations")
        return str(rel.parent), tdir / rel
    slug = spec.removesuffix(".md")
    container, _, name = slug.rpartition("/")
    if name in ("MEMORY", "EXPORTS"):
        return Finding(ERROR, "mv-not-memory", spec, "an index, not a memory")
    hits = [f for f in tdir.rglob(f"{name}.md")
            if not container or str(f.parent.relative_to(tdir)) == container]
    if not hits:
        return Finding(ERROR, "mv-no-memory", spec, "no territory memory by that name")
    if len(hits) > 1:
        return Finding(ERROR, "mv-ambiguous", spec, "in " + ", ".join(
            str(f.parent.relative_to(tdir)) for f in hits) + "; say which as area/name/slug")
    return str(hits[0].parent.relative_to(tdir)), hits[0]


def plan_files(root: Path, specs: list[str], dest: str) -> FileMove | list[Finding]:
    """Everything moving these memories into `dest` would change, or why it can't happen."""
    from claude_hybrid_memory.render import markers
    from claude_hybrid_memory.store import parse_frontmatter

    tdir = root / "territories"
    errs: list[Finding] = []
    if not (tdir / dest / "MEMORY.md").is_file():
        errs.append(Finding(ERROR, "mv-no-territory", dest, "no such territory"))
    fm = FileMove(dest=dest)
    for spec in specs:
        got = _resolve(tdir, spec)
        if isinstance(got, Finding):
            errs.append(got)
            continue
        src, f = got
        if src == dest:
            errs.append(Finding(ERROR, "mv-same-territory", spec, f"already in {dest}"))
        elif (tdir / dest / f.name).exists():
            errs.append(Finding(ERROR, "mv-target-exists", spec, f"{dest} has a {f.name}"))
        elif any(f == g for _, g in fm.files):
            errs.append(Finding(ERROR, "mv-duplicate", spec, "named twice"))
        else:
            fm.files.append((src, f))
    if errs:
        return errs

    pats = []
    for src, f in fm.files:
        old, new = f"{src}/{f.stem}", f"{dest}/{f.stem}"
        tok = _token(old)
        pats.append(re.escape(old))
        for p in sorted(tdir.rglob("*.md")):
            text = _text(fm, p)
            _, end = _frontmatter_span(text)
            lines = text[:end].split("\n")
            in_sup = False
            for i, ln in enumerate(lines):
                if key := re.match(r"^\s*([\w-]+):", ln):
                    in_sup = key.group(1) == "supersedes"
                if in_sup:
                    lines[i] = tok.sub(new, ln)
            if end and (edited := "\n".join(lines) + text[end:]) != text:
                fm.edits[p] = edited
        index = (tdir / src / "MEMORY.md").read_text(encoding="utf-8")
        if not markers(index) and (
                m := re.search(ENTRY_LINE.format(re.escape(f.name)), index, re.M)):
            fm.carried.append(m.group(0))
        meta, _, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        if str(meta.get("role") or "").strip() == "gate":
            fm.notes.append(Finding(WARN, "mv-gate", f"territories/{src}/{f.name}",
                                    f"a gate: move its text from {src}'s GATES section to "
                                    f"{dest}'s, and check GATES.md's pointer"))
    _prose(fm, root, re.compile(rf"(?<![\w.-])(?:{'|'.join(pats)})(?![\w-])"))
    return fm


def _after_last_entry(text: str, lines: list[str]) -> str:
    """`lines` after a hand-written index's last entry. Most hand-written indexes group
    entries under topic headings with no `## MEMORIES`, so a new section at the end would
    strand the lines away from the rest."""
    entries = list(re.finditer(r"^- \[[^\]]*\]\([^)/]+\.md\).*$", text, re.M))
    last = entries[-1] if entries else None
    if last is None:
        return text.rstrip("\n") + "\n\n## MEMORIES\n" + "\n".join(lines) + "\n"
    return text[:last.end()] + "\n" + "\n".join(lines) + text[last.end():]


def describe_files(root: Path, fm: FileMove, done: bool) -> list[Finding]:
    verb = "moved" if done else "would move"
    out = [Finding(INFO, "mv-file", f"territories/{src}/{f.name}",
                   f"{verb} to territories/{fm.dest}/{f.name}") for src, f in fm.files]
    out += [Finding(INFO, "mv-edit", str(p.relative_to(root)),
                    "rewritten" if done else "would rewrite") for p in sorted(fm.edits)]
    return out + fm.notes


def apply_files(root: Path, legacy: Path, fm: FileMove) -> list[Finding]:
    """Write the move. Each index is reindexed: a rendered one re-renders, a hand-written
    one loses the moved lines and the destination gains them as they were written."""
    from claude_hybrid_memory.migrate import apply

    tdir = root / "territories"

    def write() -> None:
        for p, text in fm.edits.items():
            p.write_text(text, encoding="utf-8")
        for _, f in fm.files:
            f.rename(tdir / fm.dest / f.name)
        index = tdir / fm.dest / "MEMORY.md"
        if fm.carried:
            from claude_hybrid_memory.render import markers
            text = index.read_text(encoding="utf-8")
            if not markers(text):
                index.write_text(_after_last_entry(text, fm.carried), encoding="utf-8")
        for src in dict.fromkeys(s for s, _ in fm.files):
            apply.reindex(root, src, frozenset(f.name for s, f in fm.files if s == src))
        apply.reindex(root, fm.dest)

    moves = {f"{src}/{f.stem}": f"{fm.dest}/{f.stem}" for src, f in fm.files}
    tok = re.compile(rf"(?<![\w.-])(?:{'|'.join(map(re.escape, moves))})(?![\w-])")
    names = " ".join(f"{fm.dest}/{f.stem}" for _, f in fm.files)
    srcs = sorted({s for s, _ in fm.files})
    back = (f"`mem mv {names} {srcs[0]} --write` moves it back" if len(srcs) == 1
            else f"`mem mv` each back to {', '.join(srcs)}")
    subject = (f"mv: {fm.files[0][1].stem} -> {fm.dest}" if len(fm.files) == 1
               else f"mv: {len(fm.files)} memories -> {fm.dest}")
    return _committed(root, legacy, "mem mv", subject, write,
                      lambda path: tok.sub(lambda m: moves[m.group(0)], path), back,
                      lambda: describe_files(root, fm, True))
