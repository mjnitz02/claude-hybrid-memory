"""Required fields, slugs, and field vocabularies."""
from __future__ import annotations

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.spec import (
    CONFIDENCES,
    KINDS,
    MODES,
    OWNERS,
    ROLES,
    SLUG_RE,
    STATUSES,
    TIERS,
    VOLATILITIES,
)
from claude_hybrid_memory.store import Memory


def check_structure(mems: list[Memory]) -> list[Finding]:
    out = []
    for m in mems:
        rel = str(m.path)
        for p in m.fm_problems:
            out.append(Finding(WARN, "frontmatter-not-yaml", rel, p))
        if not m.meta:
            out.append(Finding(ERROR, "no-frontmatter", rel, "no parseable frontmatter"))
            continue
        if not m.name:
            out.append(Finding(ERROR, "missing-name", rel,
                               "no `name:` field; link target falls back to filename (fixable)"))
        elif m.name != m.stem:
            out.append(Finding(ERROR, "name-filename-mismatch", rel,
                               f"name: {m.name!r} != filename stem {m.stem!r} (fixable)"))
        if not SLUG_RE.match(m.slug):
            out.append(Finding(ERROR, "bad-slug", rel,
                               f"slug {m.slug!r} is not kebab-case (fixable)"))
        if not str(m.meta.get("description") or "").strip():
            out.append(Finding(ERROR, "missing-description", rel,
                               "no `description:`; the router hook would be empty"))
        kind = str(m.meta.get("kind") or "").strip()
        if not kind:
            out.append(Finding(WARN, "missing-kind", rel, "no `kind:`; assuming territory"))
        elif kind not in KINDS:
            out.append(Finding(ERROR, "bad-kind", rel, f"kind {kind!r} not in {sorted(KINDS)}"))
        if m.volatility is None:
            # Not a defect: freshness defaults this to `slow` (90d), which is a safe
            # middle. Left as INFO so 140 migrated legacy files do not drown the report
            # and train everyone to ignore the warn level.
            out.append(Finding(INFO, "no-volatility", rel,
                               "no `volatility:` and no `status:` to derive it from; "
                               "defaulting to slow (90d). Classify during a retrospective."))
        elif m.volatility not in VOLATILITIES:
            out.append(Finding(ERROR, "bad-volatility", rel,
                               f"volatility {m.volatility!r} not in {sorted(VOLATILITIES)}"))
        for fld, allowed in (("status", STATUSES), ("role", ROLES), ("confidence", CONFIDENCES),
                             ("owner", OWNERS), ("mode", MODES), ("tier", TIERS)):
            v = m.meta.get(fld)
            if v and str(v).strip() not in allowed:
                lvl = ERROR if fld == "status" else WARN
                out.append(Finding(lvl, f"bad-{fld}", rel,
                                   f"{fld} {str(v)!r} not in {sorted(allowed)}"))
        if m.meta.get("last_verified") and m.last_verified is None:
            out.append(Finding(ERROR, "bad-date", rel,
                               f"last_verified {m.meta['last_verified']!r} is not YYYY-MM-DD"))
    return out
