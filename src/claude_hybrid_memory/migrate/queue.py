"""Stage 5 (fast-adoption §8): the refine queue.

The queue is derived, never edited: the audit findings that need judgment, the summary
flags on every landed file, and `verify:` candidates from the summarizer and a heuristic.
Working an item changes the store, and the next `mem refine queue` drops it because the
thing it was derived from is gone. No state file records what was done.

How each item drops:
  audit finding             the audit stops reporting it
  description               the description differs from the one that landed
  shape, low-confidence     the body differs from the one that landed
  standing/gate-candidate,  the file is no longer at that path (promoted, moved, archived)
  territory-hint, index-only
  verify                    the memory carries `verify:`, or is `tier: record`. Only the
                            summarizer's claims queue; the §8 heuristic ranks them
Every item also drops when its memory is superseded. One Matt declines is suppressed by
writing its key, in backticks as `refine:<key>`, into RETRO.md with the reason.

"As landed" is the file once `mem migrate apply` finished with its silo: at the decisions
commit, which rewrote links and descriptions, or the landing commit when there was nothing
to decide (apply.py). It is read from the store's history, so there is nothing to keep in
step with what git already says happened.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from claude_hybrid_memory import storegit
from claude_hybrid_memory.fix import desired_slug
from claude_hybrid_memory.migrate import plan as P
from claude_hybrid_memory.migrate import workdir
from claude_hybrid_memory.store import parse_frontmatter, scan_store

AUDIT_CODES = ("split-candidate", "possible-duplicate", "frontmatter-not-yaml", "stale-live",
               "superseded-still-indexed", "budget-high", "budget-always-stale")
SHAPES = ("build-diary", "dated-snapshot", "accreted")

# Lower works first. The always-loaded layer costs every session, so promotions lead;
# verify candidates the summarizer and the heuristic agree on come before either alone.
RANK = {"gate-candidate": 0, "standing-candidate": 1, "verify-both": 2, "stale-live": 3,
        "description": 4, "frontmatter-not-yaml": 5, "superseded-still-indexed": 5,
        "budget-high": 5, "budget-always-stale": 5, "split-candidate": 6, "shape": 7,
        "possible-duplicate": 8, "verify-summary": 9, "index-only": 10,
        "low-confidence": 11, "territory-hint": 12}

DECLINED_RE = re.compile(r"`refine:([^`]+)`")

# Claims that go stale on their own (§8). Each is a signal to write a recipe, not a verdict.
HEURISTIC = [
    ("commit sha", re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")),
    ("PR or issue", re.compile(r"\b(?:PR|pull|issue)\s*#?\d+\b|(?<![\w&/])#\d{2,5}\b", re.I)),
    ("uncommitted", re.compile(r"\buncommitted\b", re.I)),
    ("as of a date", re.compile(r"\bas of \d{4}-\d{2}-\d{2}\b", re.I)),
    ("phase with a status", re.compile(
        r"\bphase\s*\d+\b[^.\n]{0,40}?\b(?:done|built|shipped|in progress|in flight|next|"
        r"pending|blocked|open)\b", re.I)),
    ("branch name", re.compile(r"\bbranch(?:es)?\s+`[^`\n]+`|`[^`\s]+`\s+branch\b", re.I)),
    ("version now", re.compile(r"\b(?:currently|now)\b[^.\n]{0,30}?\bv?\d+\.\d+(?:\.\d+)?\b",
                               re.I)),
]


@dataclass
class Item:
    key: str
    type: str
    path: str          # store-relative
    territory: str
    rank: int
    detail: str
    source: str        # audit | summary | summary+heuristic


def path(root: Path) -> Path:
    return workdir(root) / "queue.json"


def declined(root: Path) -> set[str]:
    f = root / "RETRO.md"
    return set(DECLINED_RE.findall(f.read_text(encoding="utf-8"))) if f.is_file() else set()


def _rel(root: Path, p: str | Path) -> str:
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return str(p)


def _territory(rel: str) -> str:
    parts = Path(rel).parts
    return "/".join(parts[1:-1]) if parts[:1] == ("territories",) else parts[0]


def latest_summaries(root: Path) -> dict[str, dict]:
    """The newest good summary of each file, by inventory id. Keys can't be recomputed
    after landing (the silo now links to the territory), so summaries are found by id."""
    out: dict[str, dict] = {}
    d = workdir(root) / "summaries"
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        rec = json.loads(f.read_text(encoding="utf-8"))
        if rec.get("kind") != "file" or rec.get("status") != "ok":
            continue
        if rec["id"] not in out or rec.get("at", "") > out[rec["id"]].get("at", ""):
            out[rec["id"]] = rec
    return out


@dataclass
class Landed:
    id: str
    entry: dict        # the plan's file entry
    territory: str     # where it lives now
    rel: str           # store-relative path now
    base: str | None   # the text as landed


def landed(root: Path, plan: dict) -> list[Landed]:
    """Every file the plan landed and did not archive, with where it is and how it
    landed. A file whose slug can't be found is skipped: something since moved it."""
    from claude_hybrid_memory.migrate import apply

    done = apply.applied(root)
    out = []
    for s in plan["silos"]:
        shas = done.get(s["silo"])
        if not shas:
            continue
        leaf = s["territory"].rsplit("/", 1)[-1]
        for e in s["files"]:
            if e["action"] == "archive":
                continue
            now = e["to"] if e["action"] == "relocate" else s["territory"]
            slug = desired_slug(e["file"][:-3])
            for cand in (f"{leaf}-{slug}", slug):     # apply.py prefixes on collision
                rel = f"territories/{now}/{cand}.md"
                if (root / rel).is_file():
                    base = storegit.read_at(root, shas[0], rel)
                    out.append(Landed(f"{s['silo']}/{e['file']}", e, now, rel,
                                      base.decode("utf-8", "replace") if base else None))
                    break
    return out


def _audit_items(root: Path, legacy: Path, today: dt.date) -> list[Item]:
    from claude_hybrid_memory import audit

    mems, routers = scan_store(root)
    out = []
    for f in audit.run_all(mems, routers, root, legacy, today):
        if f.code not in AUDIT_CODES:
            continue
        rel = _rel(root, f.path)
        out.append(Item(f"{f.code}:{rel}", f.code, rel, _territory(rel), RANK[f.code],
                        f.message, "audit"))
    return out


def _summary_items(root: Path, plan: dict, superseded: set[str]) -> tuple[list[Item],
                                                                          dict[str, list]]:
    """Summary flags still open, and the summarizer's verify claims by path."""
    sums = latest_summaries(root)
    have = P.territories(root)
    items, claims = [], {}
    for la in landed(root, plan):
        if la.rel in superseded:
            continue
        s = (sums.get(la.id) or {}).get("summary")
        if not s:
            continue
        text = (root / la.rel).read_text(encoding="utf-8")
        meta, body, _ = parse_frontmatter(text)
        bmeta, bbody, _ = parse_frontmatter(la.base) if la.base else ({}, None, [])

        def add(t: str, detail: str, la: Landed = la):
            items.append(Item(f"{t}:{la.rel}", t, la.rel, la.territory, RANK[t], detail,
                              "summary"))

        if (s["description_verdict"] != "good" and la.entry.get("description") != "proposed"
                and meta.get("description") == bmeta.get("description")):
            add("description", f"summary says {s['description_verdict']}; it read: "
                               f"{s['conclusion']}")
        shapes = [x for x in s["shape"] if x in SHAPES]
        if shapes and body == bbody:
            add("shape", ", ".join(shapes))
        if s["confidence"] == "low" and body == bbody:
            add("low-confidence", f"the summarizer was unsure; it read: {s['conclusion']}")
        if "index-only" in s["shape"]:
            add("index-only", f"its conclusion may say it all: {s['conclusion']}")
        if s["kind"] in ("standing-candidate", "gate-candidate"):
            add(s["kind"], s["conclusion"])
        hint = P._norm(s.get("territory_hint"))
        if hint and hint != la.territory and hint in have:
            add("territory-hint", f"summary suggests {hint}")
        if s["verify"]:
            claims[la.rel] = s["verify"]
    return items, claims


def _verify_items(root: Path, claims: dict[str, list], superseded: set[str]) -> list[Item]:
    """The summarizer's claims, ranked up where the heuristic agrees. Heuristic hits alone
    are not queued: on this store 113 of 159 were provenance footnotes ("checked against
    `25983e9`"), which is noise §14 says to cut at the source."""
    mems = {_rel(root, m.path): m for m in scan_store(root)[0]}
    out = []
    for rel, said in claims.items():
        m = mems.get(rel)
        if (m is None or rel in superseded or m.meta.get("verify")
                or str(m.meta.get("tier") or "") == "record"):
            continue
        hits = [f"{label} `{mt.group(0)}`" for label, rx in HEURISTIC
                if (mt := rx.search(m.body))]
        out.append(Item(f"verify:{rel}", "verify", rel, _territory(rel),
                        RANK["verify-both" if hits else "verify-summary"],
                        "; ".join([f"{c['claim']} [{c['identifier']}]" for c in said] + hits),
                        "summary+heuristic" if hits else "summary"))
    return out


def build(root: Path, legacy: Path, today: dt.date | None = None,
          territory: str | None = None) -> dict:
    from claude_hybrid_memory import audit

    today = today or dt.date.today()
    superseded = {_rel(root, p) for p in audit.superseded_paths(root)}
    items = _audit_items(root, legacy, today)
    plan = P.load(root)
    claims: dict[str, list] = {}
    if plan:
        more, claims = _summary_items(root, plan, superseded)
        items += more
    items += _verify_items(root, claims, superseded)
    skip = declined(root)
    open_ = [i for i in items if i.key not in skip]
    kept = [i for i in open_ if not territory or i.territory == territory
            or i.territory.startswith(territory + "/")]
    kept.sort(key=lambda i: (i.rank, i.territory, i.path))
    return {"generated": dt.datetime.now().isoformat(timespec="seconds"),
            "territory": territory, "declined": len(items) - len(open_),
            "items": [asdict(i) for i in kept]}


def write(root: Path, q: dict) -> Path:
    f = path(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(q, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return f
