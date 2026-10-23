"""Rendered territory indexes (direction §6, Phase 4): the MEMORIES section of a territory's
MEMORY.md, generated from the memories themselves.

The harness auto-loads only the first 200 lines of MEMORY.md, and a hand-written index
grows a line per memory until it hits that cap (console/tools sat at 195). Rendering makes
the index a function of the markdown: each memory's `description:` is its line, its
`group:` places it under a heading, and the territory's own `groups:` frontmatter orders
the headings. Everything outside the markers stays hand-written and is never touched.

    <!-- mem:render begin ... -->
    ### Group
    - [slug](slug.md) — description
    - Records and history: [a](a.md) · [b](b.md)
    <!-- mem:render end -->

What does not get a line of its own:
  - a superseded memory: dropped, since the memory superseding it is the current word;
  - a `tier: record` or `status: HISTORICAL` memory: one compact line per group, so it
    stays reachable from the index at a fraction of the lines. (direction §6 says records stay
    out "unless hot"; that needs read counts, which wait for Phase 2's events.)

A description longer than 160 bytes is cut at a word boundary with "…" on its index line:
an index directs to its memory, it does not stand in for it.

Budget: the MEMORIES section warns past 100 lines and errors past 150; the hand-written
head above it is not counted. The whole file still errors past the harness's 200 lines,
since that is truncation, not policy.

Adoption (`--adopt`) is the one-off migration of a hand-written index. The dry run lists
every hand-written line whose words the description lacks. That is for information:
the description carries the meaning, and a detail it drops is a read of the memory away.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from claude_hybrid_memory.findings import ERROR, WARN, Finding
from claude_hybrid_memory.store import load_file, parse_frontmatter

BEGIN = "<!-- mem:render begin"
END = "<!-- mem:render end -->"
BEGIN_LINE = (f"{BEGIN}: generated from each memory's description and group; "
              "edit those, then `mem render` -->")
LINE_CAP = 200          # the harness loads only the first 200 lines
BYTE_CAP = 25_000       # and at most 25 KB (format-spec.md)
BYTE_WARN = 24_000      # a kilobyte short of it: room for a few more lines, not many
LINE_DESC = 160         # bytes of description per index line; longer is cut at a word, with …
MEM_WARN = 100          # lines of the MEMORIES section itself: the ideal ceiling
MEM_CAP = 150           # and the hard one; the hand-written head above it is not counted
OTHER = "Other"
RECORDS = "Records and history"

SECTION_RE = re.compile(r"^## MEMORIES\b.*$", re.M)
ENTRY_RE = re.compile(
    r"^- \[(?P<title>[^\]]*)\]\((?P<file>[^)]+\.md)\)\s*(?:[—–-]+\s*)?(?P<gloss>.*)$")


@dataclass
class Entry:
    slug: str
    file: str
    description: str
    group: str | None
    compact: bool        # a record or HISTORICAL: one shared line per group


@dataclass
class Territory:
    name: str
    index: Path
    entries: list[Entry]
    groups: list[str]                     # the order from MEMORY.md frontmatter
    superseded: list[str] = field(default_factory=list)


def one_line(s) -> str:
    return " ".join(str(s or "").split())


def load(root: Path, name: str, superseded: set[str] | None = None) -> Territory:
    """A territory's memories as the render sees them. `superseded` is store-relative
    paths; computed from the whole store when not given, since a chain can cross
    territories."""
    from claude_hybrid_memory.audit.relations import store_graph

    d = root / "territories" / name
    if superseded is None:
        superseded = store_graph(root).superseded()
    entries, gone = [], []
    for f in sorted(d.glob("*.md")):
        if f.name in ("MEMORY.md", "EXPORTS.md"):
            continue
        m = load_file(f, "store", name)
        if f"territories/{name}/{f.name}" in superseded:
            gone.append(m.slug)
            continue
        tier = one_line(m.meta.get("tier")).lower()
        status = one_line(m.meta.get("status")).upper()
        entries.append(Entry(m.slug, f.name, one_line(m.meta.get("description")),
                             one_line(m.meta.get("group")) or None,
                             tier == "record" or status == "HISTORICAL"))
    meta, _, _ = parse_frontmatter((d / "MEMORY.md").read_text(encoding="utf-8",
                                                              errors="replace"))
    groups = meta.get("groups") or []
    groups = [one_line(g) for g in groups] if isinstance(groups, list) else []
    return Territory(name, d / "MEMORY.md", entries, groups, gone)


def clip(s: str, limit: int = LINE_DESC) -> str:
    """`s` in at most `limit` UTF-8 bytes, cut at a word boundary and ended with "…". An
    index line directs to its memory; it does not stand in for it, so the whole description
    stays in the file and only the line is short."""
    if len(s.encode()) <= limit:
        return s
    room = limit - len("…".encode())
    head = s.encode()[:room].decode(errors="ignore")
    if " " in head and not s[len(head)].isspace():
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:—–-(") + "…"


def render_section(t: Territory) -> str:
    """The text between the markers."""
    by: dict[str | None, list[Entry]] = {}
    for e in t.entries:
        by.setdefault(e.group, []).append(e)
    named = [g for g in by if g is not None]
    order = [g for g in t.groups if g in by] + sorted(g for g in named if g not in t.groups)
    if None in by:
        order.append(None)
    lines = []
    for g in order:
        if named:
            lines.append(f"### {g or OTHER}")
        es = sorted(by[g], key=lambda e: e.slug)
        lines += [f"- [{e.slug}]({e.file}) — {clip(e.description)}" for e in es if not e.compact]
        compact = [e for e in es if e.compact]
        if compact:
            lines.append(f"- {RECORDS}: " + " · ".join(f"[{e.slug}]({e.file})" for e in compact))
    return "\n".join(lines) + "\n" if lines else ""


def markers(text: str) -> tuple[int, int] | None:
    """(start, end) offsets of the rendered body: just past the begin line, and the start
    of the end line. None when the file has never been adopted."""
    b = text.find(BEGIN)
    if b == -1:
        return None
    start = text.find("\n", b) + 1
    end = text.find(END, start)
    if start == 0 or end == -1:
        return None
    return start, end


def rendered(root: Path) -> list[str]:
    """Territories whose MEMORY.md carries the markers."""
    tdir = root / "territories"
    if not tdir.is_dir():
        return []
    return [str(p.parent.relative_to(tdir)) for p in sorted(tdir.rglob("MEMORY.md"))
            if markers(p.read_text(encoding="utf-8", errors="replace"))]


def render(root: Path, name: str, write: bool = True,
           superseded: set[str] | None = None) -> tuple[str, str]:
    """(current text, rendered text) of an adopted territory's MEMORY.md; writes when
    they differ and `write` is set."""
    t = load(root, name, superseded)
    text = t.index.read_text(encoding="utf-8")
    s, e = markers(text)
    new = text[:s] + render_section(t) + text[e:]
    if write and new != text:
        t.index.write_text(new, encoding="utf-8")
    return text, new


def render_all(root: Path) -> list[str]:
    """Re-render ALWAYS.md and every adopted territory; the names of those that changed."""
    from claude_hybrid_memory.audit.relations import store_graph
    from claude_hybrid_memory.hooks import session_start

    changed = [session_start.ALWAYS] if session_start.write_always(root) else []
    names = rendered(root)
    if not names:
        return changed
    sup = store_graph(root).superseded()
    for n in names:
        old, new = render(root, n, True, sup)
        if old != new:
            changed.append(n)
    return changed


def check(root: Path, names: list[str] | None = None) -> list[Finding]:
    """Every territory index against the harness cap; every adopted one against its render;
    and, on a whole-store check, ALWAYS.md against the layer it is rendered from."""
    from claude_hybrid_memory.audit.relations import store_graph
    from claude_hybrid_memory.hooks import session_start

    out = []
    always = root / session_start.ALWAYS
    want = session_start.layer(root)
    # a missing ALWAYS.md is `mem budget`'s to report; the hook writes one at session start
    if not names and want and always.is_file() and session_start.read(always) + "\n" != want:
        out.append(Finding(WARN, "render-stale", str(always),
                           "differs from MACHINE.md + GATES.md + standing/ + ROUTER.md as "
                           "they are now, so sessions load an old layer; `mem render` "
                           "rewrites it"))
    tdir = root / "territories"
    if not tdir.is_dir():
        return out
    adopted = set(rendered(root))
    sup = store_graph(root).superseded() if adopted else set()
    for p in sorted(tdir.rglob("MEMORY.md")):
        name = str(p.parent.relative_to(tdir))
        if names and name not in names:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if name in adopted:
            _, new = render(root, name, False, sup)
            if new != text:
                out.append(Finding(WARN, "render-stale", str(p),
                                   "the rendered MEMORIES section differs from what the "
                                   "memories say now (a description or group changed, or "
                                   "the section was hand-edited); `mem render` rewrites it"))
            text = new
        out += budget(p, text)
    return out


def nlines(text: str) -> int:
    return text.count("\n") + (bool(text) and not text.endswith("\n"))


def memory_lines(text: str) -> int:
    """Lines of the `## MEMORIES` section, up to the next `## ` heading. The gates and
    contract above it are the territory's own business and are not budgeted here."""
    m = SECTION_RE.search(text)
    if not m:
        return 0
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return nlines(text[m.start():m.end() + nxt.start() if nxt else len(text)])


def budget(p: Path, text: str) -> list[Finding]:
    lines, size = nlines(text), len(text.encode())
    out = []
    if lines > LINE_CAP or size > BYTE_CAP:
        out.append(Finding(ERROR, "index-over-cap", str(p),
                           f"{lines} lines, {size:,} bytes: the harness loads only the first "
                           f"{LINE_CAP} lines / {BYTE_CAP:,} bytes, so the tail is never seen"))
    if not out and size > BYTE_WARN:
        out.append(Finding(WARN, "index-near-cap", str(p),
                           f"{size:,} of the harness's {BYTE_CAP:,} bytes"))
    mem = memory_lines(text)
    if mem > MEM_CAP:
        out.append(Finding(ERROR, "memories-over-cap", str(p),
                           f"the MEMORIES section is {mem} lines, over the {MEM_CAP}-line cap"))
    elif mem > MEM_WARN:
        out.append(Finding(WARN, "memories-over-target", str(p),
                           f"the MEMORIES section is {mem} lines, over the {MEM_WARN}-line target"))
    return out


# --- adoption --------------------------------------------------------------------------

STOP = set("""a an and the of to in on at by for from with without into onto is are was
were be been it its this that these those as or not no but so if then than via per all any
every one only just also still now here there what which who how why when where do does
did can never""".split())
WORD_RE = re.compile(r"[a-z0-9][a-z0-9._/-]*[a-z0-9]|[a-z0-9]")


def words(s: str) -> list[str]:
    out = []
    for w in WORD_RE.findall(s.lower().replace("`", " ").replace("*", " ")):
        if w in STOP or len(w) < 2 or len(w) < 3 and not w.isdigit():
            continue
        out.append(w)
    return list(dict.fromkeys(out))


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def uncovered(index: str, description: str) -> list[str]:
    """Words of the index line the description lacks. A hyphenated word counts as present
    whole ("keep-list") or by all of its parts ("keep list"), and the other way round."""
    have = set()
    for w in words(description):
        have.add(_stem(w))
        have.update(_stem(x) for x in w.split("-") if x)
    return [w for w in words(index)
            if _stem(w) not in have and not all(_stem(x) in have for x in w.split("-") if x)]


@dataclass
class Line:
    group: str | None
    title: str
    file: str
    gloss: str
    slug: str = ""
    description: str = ""
    missing: list[str] = field(default_factory=list)


@dataclass
class Adoption:
    territory: str
    groups: list[str]
    lines: list[Line]
    prose: list[str]                 # non-entry lines in the section, which a render drops
    ghosts: list[str]                # index links to files that do not exist
    unlisted: list[str]              # memories with no index line: they land under Other
    superseded: list[str]
    before: int
    after: str                       # the whole MEMORY.md as --write would leave it
    compact: list[str]

    @property
    def after_lines(self) -> int:
        return self.after.count("\n")


def parse_section(text: str) -> tuple[int, int, list[Line], list[str]] | None:
    """The hand-written `## MEMORIES` section: its span, entries and leftover prose."""
    m = SECTION_RE.search(text)
    if not m:
        return None
    nxt = re.compile(r"^## ", re.M).search(text, m.end())
    end = nxt.start() if nxt else len(text)
    group, lines, prose = None, [], []
    for ln in text[m.end():end].splitlines():
        if ln.startswith("### "):
            group = ln[4:].strip()
        elif e := ENTRY_RE.match(ln):
            lines.append(Line(group, e["title"].strip(), Path(e["file"]).name,
                              e["gloss"].strip()))
        elif ln.strip():
            prose.append(ln)
    return m.start(), end, lines, prose


def adopt(root: Path, name: str) -> Adoption:
    """What `--adopt --write` would do, without doing it."""
    from claude_hybrid_memory.audit.relations import store_graph

    t = load(root, name, store_graph(root).superseded())
    text = t.index.read_text(encoding="utf-8")
    if markers(text):
        raise ValueError(f"{name} is already rendered; `mem render {name}` re-renders it")
    parsed = parse_section(text)
    if parsed is None:
        raise ValueError(f"{t.index} has no `## MEMORIES` section to adopt")
    start, end, lines, prose = parsed
    by_file = {e.file: e for e in t.entries}
    sup_files = {f"{s}.md" for s in t.superseded}
    ghosts, seen = [], set()
    for ln in lines:
        e = by_file.get(ln.file)
        if e is None:
            if ln.file not in sup_files:
                ghosts.append(ln.file)
            continue
        if ln.file in seen:
            continue                  # listed twice: the first heading wins
        seen.add(ln.file)
        ln.slug, ln.description = e.slug, e.description
        ln.missing = uncovered(f"{ln.title} {ln.gloss}", f"{e.description} {e.slug}")
        e.group = ln.group
    groups = list(dict.fromkeys(ln.group for ln in lines if ln.group))
    t.groups = groups
    unlisted = [e.slug for e in t.entries if e.file not in seen]
    section = "## MEMORIES\n" + BEGIN_LINE + "\n" + render_section(t) + END + "\n"
    after = text[:start] + section + ("\n" + text[end:].lstrip("\n") if text[end:].strip() else "")
    after = with_groups(after, groups)
    return Adoption(name, groups, [ln for ln in lines if ln.slug], prose, ghosts, unlisted,
                    t.superseded, text.count("\n"), after,
                    [e.slug for e in t.entries if e.compact])


def write_adoption(root: Path, a: Adoption) -> int:
    """Apply an adoption: `group:` into each listed memory, then the rendered index."""
    d = root / "territories" / a.territory
    n = 0
    for ln in a.lines:
        if not ln.group:
            continue
        p = d / ln.file
        text = p.read_text(encoding="utf-8")
        new = set_field(text, "group", json.dumps(ln.group, ensure_ascii=False))
        if new != text:
            p.write_text(new, encoding="utf-8")
            n += 1
    (d / "MEMORY.md").write_text(a.after, encoding="utf-8")
    return n


def set_field(text: str, key: str, value: str) -> str:
    """`text` with top-level `key: value` in its frontmatter, replacing any old scalar, and
    every other byte left as it was."""
    end = text.find("\n---", 3)
    if not text.startswith("---") or end == -1:
        raise ValueError("no frontmatter")
    head = [ln for ln in text[:end].split("\n") if not re.match(rf"{key}\s*:", ln)]
    return "\n".join(head + [f"{key}: {value}"]) + text[end:]


def with_groups(text: str, groups: list[str]) -> str:
    """MEMORY.md with its frontmatter `groups:` set: a one-line flow list, because every
    line here counts against the same 200."""
    if not groups:
        return text
    end = text.find("\n---", 3)
    if not text.startswith("---") or end == -1:
        return text
    out, skip = [], False
    for ln in text[:end].split("\n"):
        if skip and ln[:1] in (" ", "\t", "-") and ln.strip():
            continue
        skip = bool(re.match(r"groups\s*:", ln))
        if not skip:
            out.append(ln)
    out.append("groups: [" + ", ".join(json.dumps(g, ensure_ascii=False) for g in groups) + "]")
    return "\n".join(out) + text[end:]
