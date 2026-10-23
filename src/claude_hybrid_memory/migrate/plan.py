"""Stage 3 (fast-adoption §6): the territory map, the one checkpoint.

Code drafts the plan from the inventory and the summaries; Matt edits it and approves it.
It lives at `<store>/migrate/plan.yaml`, not in `.cache/`: his edits are decisions, not
derived data, so the store's own commits keep every version of it.

Code, not the model, decides what it can check: whether a territory already exists,
whether a relocation target is a real territory. The run on 2026-10-23 named the same
router line "existing" once and "new" once, so the model's label is not used.

Approval is a hash of the plan's decisions. Editing anything after approving voids it, and
stage 4 refuses an unapproved plan, so the checkpoint is enforced, not remembered.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import yaml

ACTIONS = ("land", "relocate", "archive")
DESCRIPTIONS = ("keep", "proposed")
# The verdicts where the summary's conclusion replaces the original description at landing.
REPLACE = ("names-subject", "missing", "stale")
TERRITORY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")

HEADER = """\
# The territory map: docs/fast-adoption §6, the one checkpoint.
#
# Drafted by `mem migrate map` from the inventory and the Sonnet summaries. Edit freely:
#   territory     where the silo's files go (new: true means it is created at landing)
#   action        land (default) | relocate (set `to:` a territory) | archive
#   description   keep | proposed (the summary's conclusion, which you may edit)
#   signals       what the draft saw; read only, never acted on
# Then `mem migrate map --approve`. Any edit after approving voids the approval.
"""


def path(root: Path) -> Path:
    return root / "migrate" / "plan.yaml"


def territories(root: Path) -> set[str]:
    tdir = root / "territories"
    return {str(m.parent.relative_to(tdir)) for m in tdir.rglob("MEMORY.md")} \
        if tdir.is_dir() else set()


def _norm(t: str | None) -> str | None:
    if not t:
        return None
    t = t.strip().strip("`").split()[0].lower()
    return t if TERRITORY_RE.match(t) else None


def draft(root: Path, inv: dict, summaries: dict[str, dict], router: str) -> dict:
    """A first plan. Every file lands, except what a summary or the inventory gives a
    reason not to; every such reason is written beside it for Matt."""
    have = territories(root)

    def summary(key: str) -> dict:
        return (summaries.get(key) or {}).get("summary") or {}

    def home(ss: dict) -> str | None:
        return _norm(ss.get("territory_existing")) or _norm(ss.get("territory_new"))

    # repo name -> territory, so a relocation hint naming a repo resolves to its home
    homes = {s["repo"].lower(): home(summary(s["silo"])) for s in inv["silos"]
             if s.get("repo") and home(summary(s["silo"]))}
    silos = []
    for s in inv["silos"]:
        ss = summary(s["silo"])
        t = home(ss)
        mode = ss.get("mode", "unknown")
        if s["workdir"] is None and mode not in ("dead", "parked"):
            mode = "parked"           # absence from this disk is not death (mode: parked)
        entry = {"silo": s["silo"], "territory": t, "new": t not in have if t else None,
                 "in_router": bool(t and re.search(rf"(?<![\w/-]){re.escape(t)}(?![\w/-])",
                                                   router)),
                 "mode": mode, "subject": ss.get("subject", ""), "files": []}
        if not ss:
            entry["signals"] = ["no silo summary: run mem migrate summarize"]
        if s["mixed_state"]:
            entry.setdefault("signals", []).append(
                f"mixed state: {', '.join(s['mixed_state'])} also in the store")
        for f in [f for f in inv["files"] if f["silo"] == s["silo"]]:
            entry["files"].append(_file_entry(f, summary(f["id"]) or None, t, homes, have,
                                              mode))
        silos.append(entry)
    return {"generated": dt.datetime.now().isoformat(timespec="seconds"),
            "approved": None, "silos": silos}


def _file_entry(f: dict, s: dict | None, home: str | None, homes: dict, have: set,
                mode: str) -> dict:
    e: dict = {"file": f["file"], "action": "land", "description": "keep"}
    signals = []
    if s is None:
        signals.append("no summary: run mem migrate summarize")
        e["signals"] = signals
        return e
    if s["description_verdict"] in REPLACE:
        e["description"] = "proposed"
        e["proposed"] = s["conclusion"]
        signals.append(f"description {s['description_verdict']}")
    if s["obsolete"]["likely"] or mode == "dead":
        e["action"] = "archive"
        e["why"] = s["obsolete"]["why"] or "the silo's summary says the project is dead"
    hint = _norm(s.get("territory_hint")) or homes.get(str(s.get("territory_hint") or "").lower())
    if e["action"] == "land" and hint and hint != home and (hint in have or hint in
                                                            homes.values()):
        e["action"] = "relocate"
        e["to"] = hint
        e["why"] = f"summary says it is about {s['territory_hint']}"
    if f["repos"]:
        signals.append(f"mentions {', '.join(f['repos'])}")
    if s.get("territory_hint") and e["action"] != "relocate":
        signals.append(f"hint: {s['territory_hint']}")
    if f["duplicates"]:
        signals.append(f"near-duplicate of {f['duplicates'][0]['id']}")
    if s["kind"] in ("standing-candidate", "gate-candidate", "machine-fact"):
        signals.append(s["kind"])
    if f["split_candidate"]:
        signals.append(f"split candidate, {f['bytes'] // 1024} KB")
    if s["confidence"] != "high":
        signals.append(f"{s['confidence']} confidence")
    if signals:
        e["signals"] = signals
    return e


def decisions(plan: dict) -> str:
    """What approval covers: every field a person decides, nothing generated or advisory."""
    keep = [{"silo": s["silo"], "territory": s.get("territory"), "mode": s.get("mode"),
             "files": [{k: f.get(k) for k in ("file", "action", "to", "description", "proposed")}
                       for f in s.get("files", [])]}
            for s in plan.get("silos", [])]
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()


def check(plan: dict, inv: dict, root: Path) -> list[str]:
    """Problems that would stop stage 4. Empty means the plan can be approved."""
    errs = []
    want = {(f["silo"], f["file"]) for f in inv["files"]}
    seen = set()
    for s in plan.get("silos", []):
        t = s.get("territory")
        if not t or not TERRITORY_RE.match(str(t)):
            errs.append(f"{s['silo']}: territory {t!r} is not an area/name")
        if s.get("mode") not in ("active", "parked", "dead", "unknown"):
            errs.append(f"{s['silo']}: mode {s.get('mode')!r}")
        for f in s.get("files", []):
            key = (s["silo"], f.get("file"))
            if key in seen:
                errs.append(f"{s['silo']}/{f.get('file')}: listed twice")
            seen.add(key)
            if key not in want:
                errs.append(f"{s['silo']}/{f.get('file')}: not in the inventory")
            if f.get("action") not in ACTIONS:
                errs.append(f"{s['silo']}/{f.get('file')}: action {f.get('action')!r}")
            if f.get("action") == "relocate" and not TERRITORY_RE.match(str(f.get("to") or "")):
                errs.append(f"{s['silo']}/{f.get('file')}: relocate needs `to:` a territory")
            if f.get("description") not in DESCRIPTIONS:
                errs.append(f"{s['silo']}/{f.get('file')}: description {f.get('description')!r}")
            if f.get("description") == "proposed" and not str(f.get("proposed") or "").strip():
                errs.append(f"{s['silo']}/{f.get('file')}: description proposed, but no text")
    errs += [f"{s}/{f}: in the inventory, missing from the plan" for s, f in sorted(want - seen)]
    return errs


def is_approved(plan: dict) -> bool:
    a = plan.get("approved") or {}
    return isinstance(a, dict) and a.get("decisions") == decisions(plan)


def approve(plan: dict) -> dict:
    return {**plan, "approved": {"at": dt.datetime.now().isoformat(timespec="seconds"),
                                 "decisions": decisions(plan)}}


def load(root: Path) -> dict | None:
    f = path(root)
    return yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else None


def write(root: Path, plan: dict) -> Path:
    f = path(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=100)
    f.write_text(HEADER + "\n" + body, encoding="utf-8")
    return f


def table(plan: dict, inv: dict) -> list[str]:
    """The map as Matt reads it: one block per territory, the exceptions under it."""
    by_t: dict[str, list[dict]] = {}
    for s in plan["silos"]:
        by_t.setdefault(s.get("territory") or "(none)", []).append(s)
    repo = {s["silo"]: s.get("repo") or s["silo"] for s in inv["silos"]}
    out = []
    for t, group in sorted(by_t.items()):
        s0 = group[0]
        state = ("NEW" if s0.get("new") else "existing") + (
            ", in router" if s0.get("in_router") else ", not in router")
        files = [f for s in group for f in s["files"]]
        n = {a: sum(1 for f in files if f["action"] == a) for a in ACTIONS}
        desc = sum(1 for f in files if f["description"] == "proposed")
        out.append(f"\n{t}  ({state})  <- " + ", ".join(
            f"{repo[s['silo']]} [{s['mode']}]" for s in group))
        out.append(f"   {n['land']} land, {n['relocate']} relocate, {n['archive']} archive; "
                   f"{desc} of {len(files)} descriptions replaced")
        for s in group:
            for sig in s.get("signals", []):
                out.append(f"   ! {repo[s['silo']]}: {sig}")
            for f in s["files"]:
                if f["action"] == "archive":
                    out.append(f"   archive   {f['file']}: {f.get('why', '')}")
                elif f["action"] == "relocate":
                    out.append(f"   relocate  {f['file']} -> {f['to']}: {f.get('why', '')}")
    return out
