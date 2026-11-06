"""The vocabulary of docs/format-spec.md: the values each field may take."""

from __future__ import annotations

import re

KINDS = {"standing", "territory"}
VOLATILITIES = {"stable", "slow", "live"}
STATUSES = {"SHIPPED", "PARKED", "STILL LIVE", "BLOCKED", "IN FLIGHT", "RESOLVED", "HISTORICAL"}
ROLES = {"gate", "reference"}
CONFIDENCES = {"asserted", "inferred"}
OWNERS = {"self", "colleague", "employer", "third-party"}
MODES = {"active", "occasional-pr", "reference", "dead-upstream", "scratch", "parked"}
TIERS = {"state", "record"}

STATUS_VOLATILITY = {
    "SHIPPED": "stable",
    "RESOLVED": "stable",
    "HISTORICAL": "stable",
    "PARKED": "slow",
    "STILL LIVE": "live",
    "BLOCKED": "live",
    "IN FLIGHT": "live",
}
STALE_AFTER = {"stable": 365, "slow": 30, "live": 14}
# Frontmatter the spec no longer has. `verify:` recipes and their `expect:` were executed by
# `mem fresh --run` until 2026-11-04, when verify-on-use made them dead weight; `mem fix`
# strips them.
OBSOLETE_FIELDS = ("verify", "expect", "unrunnable")

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
INDEX_LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")

# Findings only a refinement pass acts on. `mem render --check`, `mem audit --refine` and the
# refine queue show them; a plain `mem audit` does not, because a session writing memories
# is never the one that should be making room or fixing a field's vocabulary.
REFINE_CODES = frozenset(
    {
        "index-degraded",
        "description-long",
        "index-over-cap",
        "index-near-cap",
        "memories-over-target",
        "memories-over-cap",
        "field-invalid",
        "missing-kind",
    }
)

# An index line names its memory one of two ways. The link form is what hand-written indexes
# and the harness's auto-memory write; the bare form is what `mem render` and `mem new` write,
# since every memory sits beside its index and `[slug](slug.md)` spent 17% of console/tools'
# rendered section saying the slug twice. Every reader takes both.
#     - [Title](slug.md) — gloss
#     - slug: gloss
#     - Records: slug slug slug         (a LIST_LABELS line: names only)
LINK_ENTRY_RE = re.compile(
    r"^- \[(?P<title>[^\]]*)\]\((?P<file>[^)]+\.md)\)\s*(?:[—–-]+\s*)?(?P<gloss>.*)$"
)
BARE_ENTRY_RE = re.compile(r"^- (?P<slug>[\w.-]+): (?P<gloss>.*)$")
LIST_LABELS = ("Records", "Names")


def index_entry(line: str) -> tuple[str, str, str] | None:
    """(file, title, gloss) of one index entry line, in either form, or None. A LIST_LABELS
    line is not an entry; `index_names` reads it."""
    if m := LINK_ENTRY_RE.match(line):
        return m["file"].rsplit("/", 1)[-1], m["title"].strip(), m["gloss"].strip()
    if (m := BARE_ENTRY_RE.match(line)) and m["slug"] not in LIST_LABELS:
        return f"{m['slug']}.md", m["slug"], m["gloss"].strip()
    return None


def index_names(text: str) -> set[str]:
    """Every memory file an index names, in any form: links anywhere, bare entries, and the
    names on a LIST_LABELS line. Over-reads on purpose (a prose bullet `- note: ...` reads as
    `note.md`), so use it for "is this memory listed", never for "does this listing exist"."""
    out = {x.rsplit("/", 1)[-1] for x in INDEX_LINK_RE.findall(text)}
    for ln in text.splitlines():
        m = BARE_ENTRY_RE.match(ln)
        if not m:
            continue
        if m["slug"] in LIST_LABELS:
            out.update(f"{s}.md" for s in m["gloss"].split() if re.fullmatch(r"[\w.-]+", s))
        else:
            out.add(f"{m['slug']}.md")
    return out


def entry_line_re(filename: str) -> re.Pattern:
    """The entry line for one file, in either form."""
    f = re.escape(filename)
    s = re.escape(filename.removesuffix(".md"))
    return re.compile(rf"^- (?:\[[^\]]*\]\((?:[^)]*/)?{f}\)|{s}:\s).*$", re.M)


# The accretion markers direction §2 counted (24 files of 296): a mutable file acting as a log.
# The phrases match in any case ("History below"); CORRECTION and SUPERSEDED only shouted, since
# in lower case they are ordinary prose.
ACCRETION_RE = re.compile(r"(?i:read bottom-up|history below)|CORRECTION|SUPERSEDED")
