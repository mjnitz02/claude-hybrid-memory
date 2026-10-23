"""Reading the store and the legacy silos into `Memory` objects."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from claude_hybrid_memory.spec import SLUG_RE, STATUS_VOLATILITY, WIKILINK_RE

STORE = Path.home() / ".claude" / "memory"
LEGACY = Path.home() / ".claude" / "projects"


@dataclass
class Memory:
    path: Path
    meta: dict
    body: str
    scope: str          # "store" | "legacy"
    container: str      # territory path, or legacy silo name
    raw: str = ""
    links: list = field(default_factory=list)
    nonlinks: list = field(default_factory=list)
    maybe: list = field(default_factory=list)
    fm_problems: list = field(default_factory=list)

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or "").strip()

    @property
    def slug(self) -> str:
        return self.name or self.stem

    @property
    def volatility(self) -> str | None:
        v = self.meta.get("volatility")
        if v:
            return str(v).strip()
        st = str(self.meta.get("status") or "").strip().upper()
        return STATUS_VOLATILITY.get(st)

    @property
    def last_verified(self) -> dt.date | None:
        return parse_date(self.meta.get("last_verified"))

    def age_days(self, today: dt.date) -> int | None:
        lv = self.last_verified
        if lv is None:
            return None
        return (today - lv).days


def parse_date(v) -> dt.date | None:
    if not v:
        return None
    s = str(v).strip().strip("\"'")
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


class _Loader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """SafeLoader that leaves dates as text. `bad-date` judges them, and a malformed one
    (`2026-13-45`) would otherwise raise ValueError from inside the loader.

    libyaml when present: about 10x faster, and identical on all 410 real blocks
    (2026-10-21) apart from the wording of three error messages."""


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in rs if tag != "tag:yaml.org,2002:timestamp"]
    for ch, rs in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def parse_frontmatter(text: str) -> tuple[dict, str, list[str]]:
    """YAML frontmatter, read so that no text is ever lost silently.

    Returns (meta, body, problems). Measured on a real store's 409 blocks
    (2026-10-21), strict YAML alone would have:
      - rejected 5 blocks outright: a line with no key (`tag-test-fodder-corpus.md`) or an
        unquoted `: ` inside a value. Those fall back to the forgiving parser;
      - truncated 4 descriptions at an unquoted ` #` (`(PR #12)`), which YAML reads as a
        comment. The value is kept as written.
    Either way the file is named in `problems`, so the audit says to quote it.
    """
    if not text.startswith("---"):
        return {}, text, []
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text, []
    block = text[3:end].lstrip("\n")
    body = text[end + 4:].lstrip("\n")
    loose = _parse_loose(block)
    try:
        meta = yaml.load(block, _Loader)
    except yaml.YAMLError as e:
        meta = None
        why = str(e).splitlines()[0]
        problems = [f"not valid YAML ({why}); read leniently -- quote the offending value"]
    else:
        problems = []
        if meta is None:
            meta = {}
        elif not isinstance(meta, dict):
            meta = None
            problems = ["frontmatter is not a YAML mapping; read leniently"]
    if meta is None:
        meta = loose
    else:
        for k, v in meta.items():
            lv = loose.get(k)
            if (isinstance(v, str) and isinstance(lv, str) and lv != v and lv.startswith(v)
                    and lv[len(v):].lstrip().startswith("#")):
                meta[k] = lv
                problems.append(f"`{k}:` has an unquoted ' #' that YAML reads as a comment; "
                                "kept the full text -- quote the value")
    # hoist legacy nested metadata
    nested = meta.get("metadata")
    if isinstance(nested, dict):
        for k, v in nested.items():
            meta.setdefault(k, v)
    return meta, body, problems


def _parse_loose(block: str) -> dict:
    """The original forgiving parser: flat `key: value` plus one nested level.

    A line with no key is skipped, not an error. Kept as the fallback for blocks strict
    YAML rejects, and as the record of what the author wrote when YAML disagrees.
    """
    meta: dict = {}
    parent = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[0] in " \t"
        m = re.match(r"^\s*([A-Za-z_][\w.-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        val = val.strip("\"'") if val else ""
        if indented and parent:
            meta.setdefault(parent, {})
            if isinstance(meta[parent], dict):
                meta[parent][key] = val
            continue
        if val == "":
            parent = key
            meta.setdefault(key, {})
        else:
            parent = None
            meta[key] = val
    return meta


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def load_file(p: Path, scope: str, container: str) -> Memory:
    raw = p.read_text(encoding="utf-8", errors="replace")
    meta, body, fm_problems = parse_frontmatter(raw)
    links, nonlinks, maybe = [], [], []
    for cap in WIKILINK_RE.findall(raw):
        t = cap.strip()
        if not t:
            continue
        # Test the RAW capture, not the stripped one. `[[ var ]]` with surrounding spaces
        # is a Jinja delimiter, never a wikilink, and stripping first made it look like the
        # valid slug "var". A real link has no internal or surrounding whitespace.
        if cap != t:
            nonlinks.append(t)
            continue
        # A wikilink target is a slug. Anything else inside double brackets is template
        # syntax, a TOML key path, or prose: Copier's `_envops` trick uses [[ var ]] as a
        # Jinja delimiter, and 10 of 11 apparent dangling links were exactly that. Treating
        # them as errors would make the category 90% noise, which trains it to be ignored.
        # Every real slug in this system is multi-word kebab. A single bare word inside
        # double brackets is prose or a placeholder ([[override]], [[floor]], [[package]]),
        # so it only counts as a link if it actually resolves; that is decided by the
        # caller, which is why single words go to a third bucket.
        if not SLUG_RE.match(t):
            nonlinks.append(t)
        elif "-" in t:
            links.append(t)
        else:
            maybe.append(t)
    return Memory(p, meta, body, scope, container, raw=raw, links=links,
                  nonlinks=nonlinks, maybe=maybe, fm_problems=fm_problems)


def scan_store(root: Path) -> tuple[list[Memory], dict]:
    mems, routers = [], {}
    tdir = root / "territories"
    if tdir.is_dir():
        for mem_md in sorted(tdir.rglob("MEMORY.md")):
            terr = str(mem_md.parent.relative_to(tdir))
            routers[terr] = load_file(mem_md, "store", terr)
            for f in sorted(mem_md.parent.glob("*.md")):
                if f.name in ("MEMORY.md", "EXPORTS.md"):
                    continue
                mems.append(load_file(f, "store", terr))
    sdir = root / "standing"
    if sdir.is_dir():
        for f in sorted(sdir.glob("*.md")):
            mems.append(load_file(f, "store", "standing"))
    return mems, routers


def scan_legacy(root: Path) -> tuple[list[Memory], dict]:
    mems, routers = [], {}
    if not root.is_dir():
        return mems, routers
    for silo in sorted(root.iterdir()):
        md = silo / "memory"
        if not md.is_dir():
            continue
        # A symlinked memory dir means this silo is already migrated: its files belong to
        # a territory and were counted by scan_store. Following it here would scan the
        # same file twice and report every slug as ambiguous with itself.
        if md.is_symlink():
            continue
        name = silo.name
        for f in sorted(md.glob("*.md")):
            if f.name == "MEMORY.md":
                routers[name] = load_file(f, "legacy", name)
            else:
                mems.append(load_file(f, "legacy", name))
    return mems, routers
