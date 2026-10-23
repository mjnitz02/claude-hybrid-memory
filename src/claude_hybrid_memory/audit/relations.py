"""`overrides:` and `supersedes:` must point at something real."""
from __future__ import annotations

from pathlib import Path

from claude_hybrid_memory import chains
from claude_hybrid_memory.findings import ERROR, WARN, Finding
from claude_hybrid_memory.spec import INDEX_LINK_RE
from claude_hybrid_memory.store import Memory, parse_frontmatter


def check_relations(mems: list[Memory]) -> list[Finding]:
    out = []
    by_slug = {m.slug: m for m in mems}
    standing = {m.slug for m in mems if str(m.meta.get("kind", "")).strip() == "standing"}
    for m in mems:
        ov = str(m.meta.get("overrides") or "").strip()
        if ov:
            # CLAUDE.md is a real layer above standing/: Matt authors it, it loads every
            # session, and duplicating its rules into standing/ would be exactly the
            # copy-paste failure this store exists to end. So an exception may name it as
            # its parent authority, and resolution stops there.
            if ov.split("#")[0].strip().upper() in ("CLAUDE.MD", "CLAUDE"):
                pass
            elif ov not in by_slug:
                out.append(Finding(ERROR, "override-target-missing", str(m.path),
                                   f"overrides: {ov} does not exist"))
            elif ov not in standing:
                out.append(Finding(ERROR, "override-target-not-standing", str(m.path),
                                   f"overrides: {ov} exists but is not kind: standing"))
    return out


def store_graph(root: Path) -> chains.Graph:
    """The chain graph straight from the markdown: what the cache derives, without it."""
    from claude_hybrid_memory.cache import discover

    nodes = []
    for rel, (p, area, container) in discover(root).items():
        try:
            meta, _, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        slug = Memory(p, meta, "", "store", container).slug
        nodes.append(chains.Node(rel, area, container, slug, chains.refs_of(meta)))
    return chains.build(nodes)


def check_chains(root: Path, routers: dict) -> list[Finding]:
    """Broken chains, and hand-written indexes still routing to a superseded memory.

    The superseded file itself is never at fault: it stays byte-identical by design
    (direction §6), and dropping out of search is derived. Its index line is the one thing that
    still has to move by hand, until Phase 4 renders the indexes."""
    if not root.is_dir():
        return []
    g = store_graph(root)
    out = [Finding(f.level, f.code, str(root / f.path), f.message) for f in g.findings]
    for old in sorted(g.superseded()):
        n = g.nodes[old]
        r = routers.get(n.container)
        if n.area != "territory" or r is None:
            continue
        if any(Path(t).name == Path(old).name for t in INDEX_LINK_RE.findall(r.raw)):
            by = ", ".join(s.key for s in g.successors(old))
            out.append(Finding(WARN, "superseded-still-indexed", str(r.path),
                               f"lists {Path(old).name}, superseded by {by}; drop its line "
                               "so the index routes to the current memory"))
    return out
