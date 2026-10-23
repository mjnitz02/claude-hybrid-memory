"""Stage 1 (fast-adoption §4): one record per file to adopt, by code alone.

Everything the later stages can know without a model is found here, so the summarizer
is asked only for judgment, and the map is built from signals rather than from reading:
which repos a file mentions (relocation), near-duplicates, claims that look live (the
heuristic half of the `verify:` decision), size and accretion.

Files are read directly, never through a tool, so no usage event is logged.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from claude_hybrid_memory.audit.dup import OVERLAP, toks
from claude_hybrid_memory.audit.split import SPLIT_BYTES
from claude_hybrid_memory.migrate import workdir
from claude_hybrid_memory.silos import silo_workdir
from claude_hybrid_memory.spec import ACCRETION_RE, INDEX_LINK_RE
from claude_hybrid_memory.store import Memory, load_file, scan_store

# The heuristic half of the verify: decision. Each names state that changes and would
# mislead if stale; a path or a name merely mentioned is not on the list, by the same rule
# the summarizer's directive gives.
LIVE_CLAIMS = {
    # not inside a UUID, URL, email, digest or path: none of those is a commit
    "sha": re.compile(r"(?<![\w\-/@.:])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}"
                      r"(?![\w\-@.])"),
    "pr-or-issue": re.compile(r"(?i)\b(?:PR|pull|issue)\s*#?\d+\b|(?<![\w&])#\d{2,}\b"),
    "uncommitted": re.compile(r"(?i)\b(?:uncommitted|unpushed|untracked|not yet merged|"
                             r"in the working tree)\b"),
    "as-of": re.compile(r"(?i)\bas of\s+(?:\d{4}-\d{2}-\d{2}|today|now)"),
    "phase-status": re.compile(r"(?i)\bphase\s+\w+\b[^.\n]{0,40}\b(?:done|landed|complete|"
                               r"shipped|in progress|started|pending)\b"),
    "currently": re.compile(r"(?i)\b(?:currently|right now)\b[^.\n]{0,60}\bv?\d+\.\d+"),
}
MAX_CLAIMS = 8
REPO_MIN = 4          # shorter names ("api", "web") match ordinary prose


@dataclass
class FileRecord:
    id: str                      # "<silo>/<file>"
    silo: str
    file: str
    path: str
    bytes: int
    sha256: str
    meta: dict
    fm_problems: list[str]
    index_line: str              # the silo MEMORY.md line that links it, if any
    links_out: list[str]
    linked_from: list[str]
    repos: list[str]             # repos named in the text, other than the silo's own
    duplicates: list[dict]       # {"id": ..., "overlap": 0.61}
    live_claims: list[dict]      # {"kind": "sha", "text": "..."}
    accretion: int
    split_candidate: bool


@dataclass
class SiloRecord:
    silo: str
    source: str                  # the memory directory read
    workdir: str | None          # None: nothing on THIS disk resolves to it
    repo: str | None             # the repo name the silo is for, where it can be told
    files: list[str] = field(default_factory=list)
    index: str = ""              # the silo's MEMORY.md, verbatim
    mixed_state: list[str] = field(default_factory=list)   # slugs also in the store


def pending_silos(legacy: Path) -> list[Path]:
    """Memory dirs still holding knowledge: a real directory with at least one memory."""
    out = []
    if not legacy.is_dir():
        return out
    for silo in sorted(legacy.iterdir()):
        md = silo / "memory"
        if md.is_dir() and not md.is_symlink() and any(
                f.name != "MEMORY.md" for f in md.glob("*.md")):
            out.append(md)
    return out


def _repo_name(silo: str, wd: Path | None) -> str | None:
    if wd is not None:
        return wd.name
    m = re.search(r"-workspaces-(.+)$", silo)
    return m.group(1) if m else None


def known_repos(root: Path, silos: list[SiloRecord]) -> set[str]:
    """Repo names worth matching: every territory's `members:` and every silo's repo."""
    names = {s.repo for s in silos if s.repo}
    tdir = root / "territories"
    for mem_md in tdir.rglob("MEMORY.md") if tdir.is_dir() else []:
        members = load_file(mem_md, "store", "").meta.get("members")
        if isinstance(members, dict):
            names.update(str(k) for k in members)
    return {n for n in names if len(n) >= REPO_MIN}


def live_claims(text: str) -> list[dict]:
    """Lines that state something checkable against the world, one hit per kind and line."""
    out, seen = [], set()
    for kind, rx in LIVE_CLAIMS.items():
        for m in rx.finditer(text):
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            if (kind, start) in seen:
                continue
            seen.add((kind, start))
            out.append({"kind": kind, "match": m.group(),
                        "text": text[start:end if end >= 0 else None].strip()[:160]})
            if len(out) >= MAX_CLAIMS:
                return out
    return out


def _jsonable(v):
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def build(root: Path, sources: list[Path]) -> dict:
    """Inventory `sources` (memory directories) against the store at `root`."""
    store_mems, _ = scan_store(root) if root.is_dir() else ([], {})
    store_slugs = {m.slug for m in store_mems if m.container != "standing"}
    silos: list[SiloRecord] = []
    mems: list[tuple[SiloRecord, Memory]] = []
    for src in sources:
        # a landed silo's files live on in memory.premigration, under the same silo name
        name = src.parent.name if src.name in ("memory", "memory.premigration") else src.name
        wd = silo_workdir(name) if name.startswith("-") else None
        s = SiloRecord(name, str(src), str(wd) if wd else None, _repo_name(name, wd))
        index = src / "MEMORY.md"
        s.index = index.read_text(encoding="utf-8", errors="replace") if index.is_file() else ""
        for f in sorted(src.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            m = load_file(f, "legacy", name)
            s.files.append(f.name)
            mems.append((s, m))
            if m.slug in store_slugs:
                s.mixed_state.append(m.slug)
        silos.append(s)

    repos = known_repos(root, silos)
    # `Users/` excluded: a repo named after the account would match every home path
    repo_rx = {r: re.compile(rf"(?<![\w-])(?<!Users/){re.escape(r)}(?![\w-])", re.I)
               for r in repos}
    by_slug = {m.slug: f"{s.silo}/{m.path.name}" for s, m in mems}
    by_slug.update({m.slug: str(m.path.relative_to(root)) for m in store_mems
                    if root in m.path.parents})
    inbound: dict[str, list[str]] = {}
    for s, m in mems:
        for t in m.links:
            inbound.setdefault(t, []).append(f"{s.silo}/{m.path.name}")
    for m in store_mems:
        for t in m.links:
            if root in m.path.parents:
                inbound.setdefault(t, []).append(str(m.path.relative_to(root)))

    others = [(f"{s.silo}/{m.path.name}", s.silo, toks(str(m.meta.get("description") or "")))
              for s, m in mems]
    others += [(str(m.path.relative_to(root)), m.container,
                toks(str(m.meta.get("description") or "")))
               for m in store_mems if root in m.path.parents]
    others = [o for o in others if len(o[2]) >= 4]

    files = []
    for s, m in mems:
        fid = f"{s.silo}/{m.path.name}"
        mine = toks(str(m.meta.get("description") or ""))
        dups = []
        if len(mine) >= 4:
            for oid, ocont, ot in others:
                if oid == fid or ocont == s.silo:
                    continue
                j = len(mine & ot) / len(mine | ot)
                if j >= OVERLAP:
                    dups.append({"id": oid, "overlap": round(j, 2)})
        index_line = next((ln.strip() for ln in s.index.splitlines()
                           if any(x == m.path.name for x in INDEX_LINK_RE.findall(ln))), "")
        raw = m.raw.encode()
        files.append(FileRecord(
            id=fid, silo=s.silo, file=m.path.name, path=str(m.path), bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), meta=_jsonable(m.meta),
            fm_problems=m.fm_problems, index_line=index_line,
            links_out=m.links, linked_from=sorted(set(inbound.get(m.slug, [])) - {fid}),
            repos=sorted(r for r, rx in repo_rx.items() if r != s.repo and rx.search(m.body)),
            duplicates=sorted(dups, key=lambda d: -d["overlap"]),
            live_claims=[] if str(m.meta.get("tier") or "") == "record" else live_claims(m.body),
            accretion=len(ACCRETION_RE.findall(m.raw)), split_candidate=len(raw) > SPLIT_BYTES))
    return {"generated": dt.datetime.now().isoformat(timespec="seconds"),
            "root": str(root), "silos": [asdict(s) for s in silos],
            "files": [asdict(f) for f in files]}


def write(root: Path, inv: dict) -> Path:
    out = workdir(root) / "inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load(root: Path) -> dict | None:
    f = workdir(root) / "inventory.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
