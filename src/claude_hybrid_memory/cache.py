"""The derived SQLite cache: `mem index`, `mem find`, `mem show`.

Every byte here comes from the markdown, so the file can be deleted at any time and is
rebuilt on the next call. Lives at <store>/.cache/index.sqlite, which the store gitignores.

Granularity is the section: a hit names the headings that matched and the line they start
on, so a session can `Read` straight to them instead of reading whole files.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from claude_hybrid_memory import chains
from claude_hybrid_memory.store import Memory, parse_frontmatter

SCHEMA = 2

# BM25 column weights, in sections_fts column order. Same weighting Claude Code 2.1.306 gives
# its own recall index (filename 3, frontmatter 3, headings 2.5, body 1; see direction §15).
WEIGHTS = (3.0, 3.0, 2.5, 1.0)

DDL = """
CREATE TABLE files(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,          -- relative to the store root
    area TEXT NOT NULL,                 -- territory | standing | archive
    container TEXT NOT NULL,            -- territory path, 'standing', or 'archive/<group>'
    slug TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    tier TEXT NOT NULL,
    last_verified TEXT NOT NULL,
    meta TEXT NOT NULL,                 -- the whole frontmatter, as JSON
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX files_slug ON files(slug);
CREATE TABLE chain(                     -- derived from every `supersedes:`; see chains.py
    new_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    old_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE
);
CREATE INDEX chain_old ON chain(old_id);
CREATE TABLE sections(
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    level INTEGER NOT NULL,             -- 0 for the text before the first heading
    heading TEXT NOT NULL,
    line INTEGER NOT NULL               -- 1-based, in the file
);
CREATE VIRTUAL TABLE sections_fts USING fts5(
    slug, description, heading, text, tokenize='porter unicode61'
);
"""

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Section:
    level: int
    heading: str
    line: int
    text: str


@dataclass
class Stats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    touched: int = 0        # mtime moved, content identical: no reindex
    unchanged: int = 0
    files: int = 0
    sections: int = 0
    ms: float = 0.0
    by_area: dict = field(default_factory=dict)


def db_path(root: Path) -> Path:
    return root / ".cache" / "index.sqlite"


def sections_of(text: str, body: str | None = None) -> list[Section]:
    """Split a whole file into sections by ATX heading, ignoring headings in code fences.

    `body` is the text after the frontmatter, when the caller has already parsed it."""
    if body is None:
        _, body, _ = parse_frontmatter(text)
    first = text[:len(text) - len(body)].count("\n") + 1
    out: list[Section] = []
    level, heading, start, buf = 0, "", first, []
    fence = None
    for i, line in enumerate(body.split("\n")):
        f = FENCE_RE.match(line)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
        m = None if fence else HEADING_RE.match(line)
        if m:
            if heading or "".join(buf).strip():
                out.append(Section(level, heading, start, "\n".join(buf).strip()))
            level, heading, start, buf = len(m.group(1)), m.group(2), first + i, []
        else:
            buf.append(line)
    if heading or "".join(buf).strip():
        out.append(Section(level, heading, start, "\n".join(buf).strip()))
    return out


def discover(root: Path) -> dict[str, tuple[Path, str, str]]:
    """Every file the cache covers: what scan_store reads, plus archive/."""
    found: dict[str, tuple[Path, str, str]] = {}
    tdir = root / "territories"
    if tdir.is_dir():
        for mem_md in sorted(tdir.rglob("MEMORY.md")):
            terr = str(mem_md.parent.relative_to(tdir))
            for f in sorted(mem_md.parent.glob("*.md")):
                if f.name not in ("MEMORY.md", "EXPORTS.md"):
                    found[str(f.relative_to(root))] = (f, "territory", terr)
    for f in sorted((root / "standing").glob("*.md")):
        found[str(f.relative_to(root))] = (f, "standing", "standing")
    adir = root / "archive"
    if adir.is_dir():
        for f in sorted(adir.rglob("*.md")):
            rel = f.relative_to(adir)
            group = rel.parts[0] if len(rel.parts) > 1 else ""
            found[str(f.relative_to(root))] = (f, "archive", f"archive/{group}".rstrip("/"))
    return found


def connect(root: Path, fresh: bool = False) -> sqlite3.Connection:
    """Open the cache. `fresh` starts from an empty file, which is what a rebuild is."""
    p = db_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(p)
    if fresh or conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
        # Derived data: a schema change is a rebuild, never a migration.
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(p) + suffix).unlink(missing_ok=True)
        conn = _open(p)
        conn.executescript(DDL)
        conn.execute(f"PRAGMA user_version = {SCHEMA}")
    return conn


def _open(p: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(p, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def refresh(conn: sqlite3.Connection, root: Path) -> Stats:
    """Bring the cache in line with the markdown: by mtime and size, then content hash."""
    t0 = time.perf_counter()
    st = Stats()
    disk = discover(root)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = {r[0]: r[1:] for r in conn.execute(
            "SELECT path, id, size, mtime_ns, hash FROM files")}
        for rel in rows.keys() - disk.keys():
            _drop(conn, rows[rel][0])
            st.removed += 1
        for rel, (p, area, container) in disk.items():
            try:
                s = p.stat()
                row = rows.get(rel)
                if row and row[1] == s.st_size and row[2] == s.st_mtime_ns:
                    st.unchanged += 1
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            h = hashlib.sha1(data).hexdigest()
            if row and row[3] == h:
                conn.execute("UPDATE files SET size=?, mtime_ns=? WHERE id=?",
                             (s.st_size, s.st_mtime_ns, row[0]))
                st.touched += 1
                continue
            if row:
                _drop(conn, row[0])
                st.updated += 1
            else:
                st.added += 1
            _add(conn, rel, p, area, container, data.decode("utf-8", "replace"),
                 s.st_size, s.st_mtime_ns, h)
        if st.added or st.updated or st.removed:
            _rebuild_chains(conn)
    st.files = conn.execute("SELECT count(*) FROM files").fetchone()[0]
    st.sections = conn.execute("SELECT count(*) FROM sections").fetchone()[0]
    st.by_area = dict(conn.execute("SELECT area, count(*) FROM files GROUP BY area"))
    st.ms = (time.perf_counter() - t0) * 1000
    return st


def _drop(conn: sqlite3.Connection, file_id: int) -> None:
    conn.execute("DELETE FROM sections_fts WHERE rowid IN "
                 "(SELECT id FROM sections WHERE file_id=?)", (file_id,))
    conn.execute("DELETE FROM files WHERE id=?", (file_id,))


def _add(conn, rel, p, area, container, text, size, mtime_ns, h) -> None:
    meta, body, _ = parse_frontmatter(text)
    slug = Memory(p, meta, body, "store", container).slug
    desc = str(meta.get("description") or "").strip()
    cur = conn.execute(
        "INSERT INTO files(path, area, container, slug, description, status, tier,"
        " last_verified, meta, size, mtime_ns, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (rel, area, container, slug, desc, str(meta.get("status") or "").strip(),
         str(meta.get("tier") or "").strip(), str(meta.get("last_verified") or "").strip(),
         json.dumps(meta, default=str), size, mtime_ns, h))
    fid = cur.lastrowid
    for i, sec in enumerate(sections_of(text, body) or [Section(0, "", 1, "")]):
        sid = conn.execute(
            "INSERT INTO sections(file_id, ord, level, heading, line) VALUES (?,?,?,?,?)",
            (fid, i, sec.level, sec.heading, sec.line)).lastrowid
        conn.execute("INSERT INTO sections_fts(rowid, slug, description, heading, text)"
                     " VALUES (?,?,?,?,?)", (sid, slug, desc, sec.heading, sec.text))


# --- chains -----------------------------------------------------------------------------

def graph(conn) -> chains.Graph:
    """The version-chain graph over every cached file, archive included."""
    # Only a file whose frontmatter mentions the key can have refs. Parsing every row's JSON
    # on each write cost the PostToolUse hook ~8 ms of its 50 ms budget (2026-10-21).
    nodes = [chains.Node(path, area, container, slug,
                         chains.refs_of(json.loads(meta)) if has else ())
             for path, area, container, slug, meta, has in conn.execute(
                 "SELECT path, area, container, slug, meta, instr(meta, '\"supersedes\"') > 0"
                 " FROM files ORDER BY path")]
    return chains.build(nodes)


def _rebuild_chains(conn) -> None:
    """Edges are re-derived whole on any change: a new file can resolve a ref that was
    dangling, or make a bare slug ambiguous, anywhere in the store."""
    ids = dict(conn.execute("SELECT path, id FROM files"))
    conn.execute("DELETE FROM chain")
    conn.executemany("INSERT INTO chain(new_id, old_id) VALUES (?,?)",
                     [(ids[new], ids[old]) for new, olds in graph(conn).older.items()
                      for old in olds])


SUPERSEDED = ("SELECT c.old_id FROM chain c JOIN files n ON n.id = c.new_id"
              " WHERE n.area != 'archive'")


def superseded_by(conn, file_id: int) -> list[str]:
    """container/slug of each live memory that supersedes this one."""
    return [f"{c}/{s}" for c, s in conn.execute(
        "SELECT n.container, n.slug FROM chain c JOIN files n ON n.id = c.new_id"
        " WHERE c.old_id = ? AND n.area != 'archive' ORDER BY n.path", (file_id,))]


# --- find -------------------------------------------------------------------------------

# A dated record or a HISTORICAL memory still answers a search, but below every current
# memory with as many words matched: in the 2026-11-04 eval, `find sillytavern docker unraid`
# put five home/unraid records above the memory that held the answer. A tier in the sort,
# not a score factor, so no amount of keyword density lifts history over current state.
HEADLINE = 3.0      # a word in the slug or description multiplies that word's score
MIN_PREFIX = 3      # words shorter than this match exactly, never as a prefix


@dataclass
class Hit:
    path: str
    area: str
    container: str
    slug: str
    description: str
    status: str
    tier: str
    last_verified: str
    score: float
    sections: list = field(default_factory=list)    # [(heading, line)], best first
    superseded_by: list = field(default_factory=list)
    matched: int = 0                                 # how many of the query's words it has
    due: str = ""                                    # PAST WINDOW marker, else ""


class Found(NamedTuple):
    hits: list
    archive_hidden: int
    superseded_hidden: int
    partial: bool       # nothing had every word; these have some
    elsewhere: int = 0  # full matches outside --territory, when it found none inside


def query_words(terms: list[str]) -> list[str]:
    """Every word in every argument, lowercased, once each. `"card reader"` is two words,
    not a phrase: the eval found every session expected that, and none guessed otherwise."""
    out: list[str] = []
    for t in terms:
        for w in re.findall(r"\w+", t.lower()):
            if w not in out:
                out.append(w)
    return out


def fts_query(terms: list[str], op: str) -> str:
    """Each term as one quoted FTS5 phrase, joined by `op`; FTS5 syntax in the input is
    never interpreted. Used by `near_duplicates`."""
    phrases = ['"' + t.replace('"', '""') + '"' for t in terms if re.search(r"\w", t)]
    return f" {op} ".join(phrases)


def _word_query(w: str) -> str:
    q = '"' + w.replace('"', '""') + '"'
    return q + " *" if len(w) >= MIN_PREFIX else q


def find(conn, terms: list[str], territory: str | None = None, include_archive=False,
         include_superseded=False, limit: int = 10, today=None) -> Found:
    """Each word matches as a prefix (`delet` finds `deletion`), anywhere in the file: one
    section need not hold them all. Files with every word come first; only when none has
    every word does it fall back to the files with the most, and says so, so a partial hit
    is never mistaken for a full one. Records and HISTORICAL memories rank below the rest.

    Archive and superseded memories are left out unless asked for, and counted, so a
    session knows there is something to ask about without paying to read it. A
    `--territory` with no full match counts the full matches elsewhere.
    """
    import datetime as dt

    from claude_hybrid_memory.audit.freshness import past_window

    words = query_words(terms)
    if not words:
        return Found([], 0, 0, False)
    ranked = _search(conn, words)
    old = {p for (p,) in conn.execute(f"SELECT path FROM files WHERE id IN ({SUPERSEDED})")}

    def visible(h):
        return (include_archive or h.area != "archive") and (
            include_superseded or h.path not in old)

    def inside(h):
        return not territory or h.container == territory or h.container.startswith(
            territory + "/")

    scoped = [h for h in ranked if inside(h)]
    full = [h for h in scoped if h.matched == len(words)]
    partial = not full and len(words) > 1
    pool = full or (scoped if partial else [])
    archived = sum(1 for h in pool if h.area == "archive" and not include_archive)
    superseded = sum(1 for h in pool if h.path in old and not include_superseded
                     and (include_archive or h.area != "archive"))
    hits = [h for h in pool if visible(h)][:limit]
    elsewhere = 0
    if territory and not hits:
        elsewhere = sum(1 for h in ranked if not inside(h) and visible(h)
                        and h.matched == len(words))
    today = today or dt.date.today()
    for h in hits:
        if h.path in old:
            fid = conn.execute("SELECT id FROM files WHERE path=?", (h.path,)).fetchone()[0]
            h.superseded_by = superseded_by(conn, fid)
        meta = json.loads(conn.execute("SELECT meta FROM files WHERE path=?",
                                       (h.path,)).fetchone()[0])
        if h.area != "archive" and h.path not in old and (due := past_window(meta, today)):
            h.due = due.marker()
    return Found(hits, archived, superseded, partial, elsewhere)


def _search(conn, words: list[str]) -> list[Hit]:
    """Every file matching any word, with `matched` and a score summed over its words (each
    word's best section), best first."""
    weights = ", ".join(map(str, WEIGHTS))
    by_file: dict[int, Hit] = {}
    secs: dict[int, dict[tuple, float]] = {}
    for w in words:
        best: dict[int, float] = {}
        for fid, heading, line, score in conn.execute(
                f"SELECT s.file_id, s.heading, s.line, bm25(sections_fts, {weights})"
                " FROM sections_fts JOIN sections s ON s.id = sections_fts.rowid"
                " WHERE sections_fts MATCH ? ORDER BY 4", (_word_query(w),)):
            best[fid] = min(best.get(fid, 0.0), score)
            if heading:
                k = (heading, line)
                d = secs.setdefault(fid, {})
                d[k] = min(d.get(k, 0.0), score)
        # A word in the slug or description is what the memory is ABOUT; body sections that
        # merely repeat it ("delete" 12 times in a procedure) otherwise outrank the one
        # memory whose conclusion it is (eval 2026-11-04: `find delet` put the standing
        # deletions rule 21st).
        for (fid,) in conn.execute(
                "SELECT DISTINCT s.file_id FROM sections_fts JOIN sections s"
                " ON s.id = sections_fts.rowid WHERE sections_fts MATCH ?",
                ("{slug description} : " + _word_query(w),)):
            if fid in best:
                best[fid] *= HEADLINE
        for fid, score in best.items():
            hit = by_file.get(fid)
            if hit is None:
                row = conn.execute(
                    "SELECT path, area, container, slug, description, status, tier,"
                    " last_verified FROM files WHERE id=?", (fid,)).fetchone()
                hit = by_file[fid] = Hit(*row, score=0.0)
            hit.matched += 1
            hit.score += score
    for fid, hit in by_file.items():
        hit.sections = [k for k, _ in sorted(secs.get(fid, {}).items(), key=lambda x: x[1])]
    return sorted(by_file.values(), key=lambda h: (-h.matched, _is_history(h), h.score, h.path))


def _is_history(h: Hit) -> bool:
    return h.tier == "record" or h.status.upper() == "HISTORICAL"


# --- near duplicates --------------------------------------------------------------------

# Calibrated 2026-10-21 by querying each of a real store's 310 live memories against
# the rest: similarity (below) had median 0.41, p95 0.63, max 0.90. Pairs at 0.70+ were
# real overlaps (a closed project and its status file telling the same story; an overview
# restating a migration); 0.55-0.65 were distinct memories on one topic. 9 of 310 clear it.
NEAR_DUP_CUT = 0.70


@dataclass
class Near:
    ratio: float
    path: str
    container: str
    slug: str
    description: str


def _terms(text: str, cap: int = 40) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        if len(t) > 2 and not t.isdigit() and t not in out:
            out.append(t)
    return out[:cap]


def near_duplicates(conn, rel: str, cut: float = NEAR_DUP_CUT, limit: int = 2) -> list[Near]:
    """Live memories that resemble `rel`, by its slug and description.

    Similarity is a neighbour's best BM25 score over the file's score against itself, so
    it is comparable across queries where raw BM25 is not. Archive and superseded memories
    are never candidates: the hint would say to supersede what already is.
    """
    row = conn.execute("SELECT id, slug, description FROM files WHERE path=?", (rel,)).fetchone()
    if row is None:
        return []
    fid, slug, desc = row
    q = fts_query(_terms(slug.replace("-", " ") + " " + desc), "OR")
    if not q:
        return []
    best: dict[int, float] = {}
    for f2, score in conn.execute(
            f"SELECT s.file_id, bm25(sections_fts, {', '.join(map(str, WEIGHTS))})"
            " FROM sections_fts JOIN sections s ON s.id = sections_fts.rowid"
            " JOIN files f ON f.id = s.file_id WHERE sections_fts MATCH ? AND f.area != 'archive'"
            f" AND f.id NOT IN ({SUPERSEDED})", (q,)):
        best[f2] = min(best.get(f2, 0.0), score)
    own = best.pop(fid, 0.0)
    if not own:
        return []
    out = []
    for f2, score in sorted(best.items(), key=lambda x: x[1]):
        ratio = score / own
        if ratio < cut or len(out) == limit:
            break
        out.append(Near(ratio, *conn.execute(
            "SELECT path, container, slug, description FROM files WHERE id=?", (f2,)).fetchone()))
    return out


# --- show -------------------------------------------------------------------------------

def resolve(conn, spec: str) -> list[tuple[str, str, str]]:
    """slug, container/slug, or a store-relative path -> [(path, container, slug)]."""
    q = "SELECT path, container, slug FROM files WHERE "
    rows = conn.execute(q + "path=?", (spec,)).fetchall()
    if not rows and "/" in spec:
        container, _, slug = spec.rpartition("/")
        rows = conn.execute(q + "container=? AND slug=?", (container, slug)).fetchall()
    if not rows:
        rows = conn.execute(q + "slug=? ORDER BY path", (spec,)).fetchall()
    return rows


def opening_paragraph(text: str) -> str:
    for sec in sections_of(text):
        for para in re.split(r"\n\s*\n", sec.text):
            if para.strip():
                return para.strip()
    return ""


def section_text(text: str, want: str) -> tuple[list[Section], str]:
    """The section whose heading matches `want` (exact, else substring; case-insensitive),
    through to the next heading at its level or above. Returns (candidates, text)."""
    secs = sections_of(text)
    w = want.strip().lower()
    cands = [s for s in secs if s.heading.lower() == w] or \
            [s for s in secs if w in s.heading.lower()]
    if len(cands) != 1:
        return cands, ""
    lines = text.split("\n")
    sec = cands[0]
    after = [s for s in secs if s.line > sec.line and 0 < s.level <= sec.level]
    end = after[0].line - 1 if after else len(lines)
    return cands, "\n".join(lines[sec.line - 1:end]).rstrip()
