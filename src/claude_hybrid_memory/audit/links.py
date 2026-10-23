"""Wikilinks, slug ambiguity, orphans, and router drift."""
from __future__ import annotations

import os

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.spec import INDEX_LINK_RE, SLUG_RE, WIKILINK_RE
from claude_hybrid_memory.store import Memory


def check_links(mems: list[Memory], routers: dict,
                superseded: frozenset = frozenset()) -> list[Finding]:
    """`superseded` is the absolute paths of superseded memories, which are unlisted and
    unlinked by design once their successor takes their index line."""
    out = []
    homes: dict[str, list[Memory]] = {}
    for m in mems:
        homes.setdefault(m.slug, []).append(m)
    for slug, ms in homes.items():
        if len(ms) < 2:
            continue
        where = ", ".join(sorted(m.container for m in ms))
        if all(m.scope == "legacy" for m in ms):
            # legacy silos are walled off, so this is not yet a live ambiguity. It is the
            # list of slugs that WILL collide the moment they share a territory.
            out.append(Finding(WARN, "slug-collides-on-migration", slug,
                               f"{len(ms)} files share this slug across: {where}"))
        else:
            out.append(Finding(ERROR, "ambiguous-slug", slug,
                               f"slug claimed by {len(ms)} files across: {where}"))
    router_text = "\n".join(r.raw for r in routers.values())
    linked_to: set[str] = set()
    for m in mems:
        for t in m.links:
            linked_to.add(t)
            if t in homes:
                continue
            pending = f"[[{t}]]" in router_text or f"]({t}.md)" in router_text
            out.append(Finding(WARN if pending else ERROR,
                               "pending-link" if pending else "dangling-link",
                               str(m.path), f"[[{t}]] resolves to nothing"
                               + (" (named in a router: pending)" if pending else "")))
    for m in mems:
        for t in m.maybe:
            if t in homes:
                m.links.append(t)   # a real single-word memory, so it is a link after all
            else:
                m.nonlinks.append(t)
    nl: dict[str, set[str]] = {}
    for m in mems:
        for t in m.nonlinks:
            nl.setdefault(t, set()).add(str(m.path))
    for t, paths in sorted(nl.items()):
        out.append(Finding(INFO, "not-a-wikilink", t,
                           f"[[{t}]] in {len(paths)} file(s) is not a slug; read as template "
                           "syntax or prose, not a link"))
    for m in mems:
        if m.container == "standing" or m.path in superseded:
            continue
        r = routers.get(m.container)
        in_router = bool(r and (m.path.name in r.raw or m.slug in r.raw))
        if m.slug not in linked_to and not in_router:
            out.append(Finding(WARN, "orphan", str(m.path),
                               "nothing links to it and no router lists it"))
    return out


def check_router_drift(mems: list[Memory], routers: dict,
                       superseded: frozenset = frozenset()) -> list[Finding]:
    out = []
    by_container: dict[str, set[str]] = {}
    exempt: dict[str, set[str]] = {}
    for m in mems:
        by_container.setdefault(m.container, set()).add(m.path.name)
        if m.path in superseded:
            exempt.setdefault(m.container, set()).add(m.path.name)
    for container, r in routers.items():
        present = by_container.get(container, set())
        # Asymmetric on purpose. A ghost means the router points at a file that should be
        # here and is not, so only markdown links count: a [[slug]] may legitimately name a
        # memory in ANOTHER territory, and check_links already validates those.
        listed = {os.path.basename(x) for x in INDEX_LINK_RE.findall(r.raw)}
        # For "unlisted", a wikilink DOES count as listing: a gate is referenced from the
        # inlined gate text by [[slug]] rather than as a markdown link.
        mentioned = listed | {t + ".md" for t in WIKILINK_RE.findall(r.raw) if SLUG_RE.match(t)}
        for missing in sorted(listed - present):
            out.append(Finding(ERROR, "router-ghost", f"{container}/MEMORY.md",
                               f"lists {missing} which does not exist"))
        for unlisted in sorted(present - mentioned - exempt.get(container, set())):
            out.append(Finding(WARN, "router-unlisted", f"{container}/{unlisted}",
                               "exists but the router does not list it"))
    return out
