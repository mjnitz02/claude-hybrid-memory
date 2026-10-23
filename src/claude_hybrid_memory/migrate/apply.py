"""Stage 4 (fast-adoption §7): land an approved plan, silo by silo.

Per silo, in order:
  1. its files go into the territory as they were, with only what `mem fix` would normalize
     (a kebab slug for the filename and `name:`, `kind: territory`), and the territory index
     is rendered. **Commit: "migrate: land <silo> as-is".** This is the rollback point.
  2. the plan's decisions: proposed descriptions, archives (with any link into an archived
     file rewritten to its archive path, so nothing dangles), relocations, and the router
     line. **Second commit**, so landing and rewriting can be undone separately.
  3. the silo's memory dir is renamed to `memory.premigration` and replaced by a symlink to
     the territory (setup.md step 5), after which it must read as migrated.
  4. no new error in `mem audit --scan store`, or the run stops there.

A slug already claimed anywhere in the store, or by another file in the plan, gets the
territory's last segment as a prefix (`travel-user-profile`), since the audit treats one
slug in two places as an error. A slug still taken after that stops the run before
anything is written.

`undo` reverts a silo's commits (new commits, history kept) and puts its directory back.
All store git goes through storegit.py.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from claude_hybrid_memory import storegit
from claude_hybrid_memory.fix import desired_slug
from claude_hybrid_memory.migrate import plan as P
from claude_hybrid_memory.render import BEGIN_LINE, END, clip, markers, one_line, render, set_field
from claude_hybrid_memory.store import parse_frontmatter, scan_store

MODES = ("active", "parked")


@dataclass
class Item:
    src: Path
    slug: str
    entry: dict            # the plan's file entry


@dataclass
class Landing:
    silo: str
    territory: str
    entry: dict            # the plan's silo entry
    items: list[Item] = field(default_factory=list)
    links: dict[str, str] = field(default_factory=dict)   # old slug -> final, this silo


def land_subject(silo: str, territory: str) -> str:
    return f"migrate: land {silo} as-is in {territory}"


def decisions_subject(silo: str) -> str:
    return f"migrate: apply the plan's decisions for {silo}"


def applied(root: Path) -> dict[str, list[str]]:
    """Landed silos and their commits, newest first, read from the store's own history:
    a silo whose latest landing commit has not been reverted since. No state file, so
    nothing to drift from what git says happened."""
    out: dict[str, list[str]] = {}
    seen: set[str] = set()
    pending: dict[str, str] = {}          # silo -> its decisions commit, seen before landing
    for sha, subj in storegit.subjects(root):
        rev = subj.startswith('Revert "')
        s = subj[len('Revert "'):-1] if rev else subj
        if m := re.match(r"migrate: apply the plan's decisions for (\S+)$", s):
            if m.group(1) not in seen and not rev:
                pending.setdefault(m.group(1), sha)
        elif m := re.match(r"migrate: land (\S+) as-is in ", s):
            silo = m.group(1)
            if silo in seen:
                continue
            seen.add(silo)
            if not rev:
                out[silo] = [x for x in (pending.get(silo), sha) if x]
    return out


def archive_group(territory: str) -> str:
    return territory.replace("/", "-")


def prepare(root: Path, plan: dict, inv: dict, only: list[str] | None = None
            ) -> tuple[list[Landing], list[str]]:
    """Every silo still to land, with final slugs; problems that stop the run first."""
    errs = []
    if not P.is_approved(plan):
        errs.append("the plan is not approved (or was edited since): mem migrate map --approve")
    errs += P.check(plan, inv, root)
    done = applied(root)
    paths = {(f["silo"], f["file"]): Path(f["path"]) for f in inv["files"]}
    store_mems, _ = scan_store(root)
    taken = {m.slug for m in store_mems}
    lands = []
    for s in plan["silos"]:
        if s["silo"] in done or (only and not any(x in s["silo"] for x in only)):
            continue
        lands.append(Landing(s["silo"], s["territory"], s,
                             [Item(paths[(s["silo"], f["file"])],
                                   desired_slug(f["file"][:-3]), f)
                              for f in s["files"] if (s["silo"], f["file"]) in paths]))
    # slugs: everything already in the store, plus every file this run lands
    wanted: dict[str, int] = {}
    for la in lands:
        for it in la.items:
            wanted[it.slug] = wanted.get(it.slug, 0) + 1
    final = set(taken)
    for la in lands:
        for it in la.items:
            if it.slug in taken or wanted[it.slug] > 1:
                new = f"{la.territory.rsplit('/', 1)[-1]}-{it.slug}"
                la.links[it.slug] = new
                it.slug = new
            if it.slug in final:
                errs.append(f"{la.silo}/{it.entry['file']}: slug {it.slug} is still taken")
            final.add(it.slug)
    return lands, errs


def _rewrite_links(text: str, links: dict[str, str]) -> str:
    for old, new in links.items():
        text = text.replace(f"[[{old}]]", f"[[{new}]]").replace(f"]({old}.md)", f"]({new}.md)")
    return text


def normalize(text: str, slug: str, links: dict[str, str]) -> str:
    """The file as it was, with only what `mem fix` would change anyway."""
    if not text.startswith("---"):
        text = f"---\nname: {slug}\nkind: territory\n---\n" + text
    else:
        text = set_field(text, "name", slug)
        meta, _, _ = parse_frontmatter(text)
        if not str(meta.get("kind") or "").strip():
            text = set_field(text, "kind", "territory")
    return _rewrite_links(text, links)


def new_index(territory: str, silos: list[dict], inv: dict, today: str) -> str:
    repos = {s["silo"]: s.get("repo") for s in inv["silos"]}
    members = []
    for s in silos:
        r = repos.get(s["silo"])
        if r:
            mode = f"{{mode: {s['mode']}}}" if s["mode"] in MODES else "{}"
            members.append(f"  {r}: {mode}")
    subject = "; ".join(dict.fromkeys(s.get("subject", "") for s in silos if s.get("subject")))
    return ("---\n" f"territory: {territory}\nconsumes: none\nconsumed_by: none\n"
            + ("members:\n" + "\n".join(members) if members else "members: {}") + "\n---\n"
            f"# {territory}\n\n{subject + '.' if subject else ''}\n\n"
            f"Created {today} by `mem migrate apply` (docs/fast-adoption.md) from "
            + ", ".join(f"`{s['silo']}`" for s in silos) + ". Landed as it was; the refine "
            "pass improves it from here.\n\n## MEMORIES\n" + BEGIN_LINE + "\n" + END + "\n")


def router_line(root: Path, territory: str, subject: str) -> str | None:
    """Bring ROUTER.md's line for `territory` up to date: a `[legacy]` line gets its count,
    a missing one is added under its area. Returns what was done, or None."""
    f = root / "ROUTER.md"
    if not f.is_file():
        return None
    text = f.read_text(encoding="utf-8")
    n = sum(1 for p in (root / "territories" / territory).glob("*.md")
            if p.name not in ("MEMORY.md", "EXPORTS.md"))
    have = re.compile(rf"^(- {re.escape(territory)}) (\[legacy\]|\(\d+\))", re.M)
    m = have.search(text)
    if m:
        if m.group(2) == f"({n})":
            return None
        f.write_text(have.sub(rf"\1 ({n})", text, count=1), encoding="utf-8")
        return f"ROUTER.md: {territory} {m.group(2)} -> ({n})"
    line = f"- {territory} ({n}) : {subject or territory}."
    area = territory.split("/", 1)[0]
    m = re.search(rf"^## {re.escape(area)}\b.*$", text, re.M)
    if m:
        nxt = text.find("\n## ", m.end())
        end = len(text) if nxt == -1 else nxt
        body = text[:end].rstrip("\n")
        text = body + "\n" + line + "\n" + text[end:]
    else:
        text = text.rstrip("\n") + f"\n\n## {area}\n{line}\n"
    f.write_text(text, encoding="utf-8")
    return f"ROUTER.md: added {territory}"


def reindex(root: Path, territory: str, moved: frozenset[str] = frozenset()) -> None:
    """Bring a territory's index up to date with its files. An adopted index is rendered.
    A hand-written one is left as Matt wrote it, except that it gains a line for each
    memory it does not list, and loses the lines of `moved`: files this landing archived
    or relocated away."""
    tdir = root / "territories" / territory
    index = tdir / "MEMORY.md"
    text = index.read_text(encoding="utf-8")
    if markers(text):
        render(root, territory)
        return
    link = re.compile(r"^- \[[^\]]*\]\(([^)/]+\.md)\)")
    kept = [ln for ln in text.split("\n")
            if not ((m := link.match(ln)) and m.group(1) in moved)]
    text = "\n".join(kept)
    listed = set(re.findall(r"\]\(([^)/]+\.md)\)", text))
    new = []
    for f in sorted(tdir.glob("*.md")):
        if f.name in ("MEMORY.md", "EXPORTS.md") or f.name in listed:
            continue
        meta, _, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        new.append(f"- [{f.stem}]({f.name}) — {clip(one_line(meta.get('description')))}")
    if new:
        text = text.rstrip("\n") + ("\n" if "## MEMORIES" in text else "\n\n## MEMORIES\n")
        text += "\n".join(new) + "\n"
    index.write_text(text, encoding="utf-8")


def errors(root: Path, legacy_dir: Path | None) -> set[tuple[str, str]]:
    from claude_hybrid_memory import audit

    mems, routers = scan_store(root)
    found = audit.run_all(mems, routers, root, legacy_dir or root / "no-legacy",
                          dt.date.today())
    return {(f.code, f.path) for f in found if f.level == "error"}


def land(root: Path, la: Landing, plan: dict, inv: dict, legacy_dir: Path | None
         ) -> dict:
    """Land one silo. Returns its applied-log record; raises on a stop."""
    today = dt.date.today().isoformat()
    tdir = root / "territories" / la.territory
    created: list[Path] = []
    try:
        if not (tdir / "MEMORY.md").is_file():
            tdir.mkdir(parents=True, exist_ok=True)
            group = [s for s in plan["silos"] if s["territory"] == la.territory]
            (tdir / "MEMORY.md").write_text(new_index(la.territory, group, inv, today),
                                            encoding="utf-8")
            created.append(tdir / "MEMORY.md")
        for it in la.items:
            dest = tdir / f"{it.slug}.md"
            if dest.exists():
                raise RuntimeError(f"{dest} exists")
            dest.write_text(normalize(it.src.read_text(encoding="utf-8", errors="replace"),
                                      it.slug, la.links), encoding="utf-8")
            created.append(dest)
        reindex(root, la.territory)
    except Exception:
        for p in reversed(created):
            p.unlink(missing_ok=True)
        raise
    c1 = storegit.commit(root, "mem migrate apply", subject=land_subject(la.silo, la.territory))
    if c1.status != "committed":
        raise RuntimeError(f"landing commit {c1.status}: {c1.detail}")

    notes, touched, moved = [], {la.territory}, set()
    for it in la.items:
        f = tdir / f"{it.slug}.md"
        e = it.entry
        if e.get("description") == "proposed":
            f.write_text(set_field(f.read_text(encoding="utf-8"), "description",
                                   json.dumps(e["proposed"], ensure_ascii=False)),
                         encoding="utf-8")
        if e["action"] == "archive":
            dest = root / "archive" / archive_group(la.territory) / f.name
            if dest.exists():
                raise RuntimeError(f"{dest} exists; archive by hand")
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.replace(dest)
            moved.add(f.name)
            why = dest.parent / "WHY-ARCHIVED.md"
            head = "" if why.is_file() else (
                f"# Archived from {la.territory}\n\nNever loaded; kept as provenance.\n\n")
            with why.open("a", encoding="utf-8") as fh:
                fh.write(head + f"- `{f.name}` — {today}, `mem migrate apply` from {la.silo}: "
                         f"{e.get('why', '')}\n")
            rel = f"archive/{archive_group(la.territory)}/{f.name}"
            n = _unlink(root, it.slug, rel)
            notes.append(f"archived {f.name}" + (f", {n} link(s) now point at {rel}" if n
                                                  else ""))
        elif e["action"] == "relocate":
            to = root / "territories" / e["to"]
            if not (to / "MEMORY.md").is_file():
                raise RuntimeError(f"relocate target {e['to']} has no MEMORY.md")
            if (to / f.name).exists():
                raise RuntimeError(f"{to / f.name} exists; relocate by hand")
            f.replace(to / f.name)
            moved.add(f.name)
            touched.add(e["to"])
            notes.append(f"relocated {f.name} -> {e['to']}")
    for t in sorted(touched):
        reindex(root, t, frozenset(moved) if t == la.territory else frozenset())
    r = router_line(root, la.territory, la.entry.get("subject", ""))
    if r:
        notes.append(r)
    c2 = storegit.commit(root, "mem migrate apply", subject=decisions_subject(la.silo))
    if c2.status not in ("committed", "clean"):
        raise RuntimeError(f"decisions commit {c2.status}: {c2.detail}")

    rec = {"territory": la.territory, "at": dt.datetime.now().isoformat(timespec="seconds"),
           "commits": [c1.sha] + ([c2.sha] if c2.status == "committed" else []),
           "files": len(la.items), "notes": notes}
    silo_dir = legacy_dir / la.silo / "memory" if legacy_dir else None
    if silo_dir and silo_dir.is_dir() and not silo_dir.is_symlink():
        pre = silo_dir.with_name("memory.premigration")
        if pre.exists():
            raise RuntimeError(f"{pre} already exists; the silo is left as it was")
        silo_dir.rename(pre)
        silo_dir.symlink_to(tdir)
        rec["premigration"] = str(pre)
    return rec


def _unlink(root: Path, slug: str, rel: str) -> int:
    """Point every `[[slug]]` in the territories at the archived file's path instead."""
    n = 0
    for p in (root / "territories").rglob("*.md"):
        text = p.read_text(encoding="utf-8")
        if f"[[{slug}]]" in text:
            n += text.count(f"[[{slug}]]")
            p.write_text(text.replace(f"[[{slug}]]", f"`{rel}`"), encoding="utf-8")
    return n


def run(root: Path, plan: dict, inv: dict, legacy_dir: Path | None, only=None,
        dry: bool = False, progress=None) -> tuple[list[dict], list[str]]:
    lands, errs = prepare(root, plan, inv, only)
    if errs or dry:
        return [{"silo": la.silo, "territory": la.territory, "dry": True,
                 "files": [(it.entry["file"], it.slug, it.entry["action"]) for it in la.items]}
                for la in lands], errs
    snap = storegit.commit(root, "mem migrate apply", subject="before mem migrate apply")
    if snap.status not in ("committed", "clean"):
        return [], [f"safety commit {snap.status}: {snap.detail}"]
    before = errors(root, legacy_dir)
    out = []
    for la in lands:
        try:
            rec = land(root, la, plan, inv, legacy_dir)
        except Exception as e:
            return out, [f"{la.silo}: {e}"]
        out.append({"silo": la.silo, **rec})
        if progress:
            progress(la.silo, rec)
        new = errors(root, legacy_dir) - before
        if new:
            return out, [f"after {la.silo}, new audit errors: "
                         + "; ".join(f"{c} {p}" for c, p in sorted(new))]
    return out, []


def undo(root: Path, silo: str, legacy_dir: Path | None) -> str:
    """Revert a landed silo's two commits and put its directory back. A later silo that
    touched the same files (a shared territory index, ROUTER.md) makes the revert conflict;
    it is then aborted with nothing changed, and that later silo is undone first."""
    shas = applied(root).get(silo)
    if not shas:
        raise RuntimeError(f"{silo} is not landed (no unreverted landing commit)")
    r = storegit.revert(root, shas)
    if r.status != "committed":
        raise RuntimeError(f"revert failed, nothing changed: {r.detail}")
    restored = False
    if legacy_dir:
        link, pre = legacy_dir / silo / "memory", legacy_dir / silo / "memory.premigration"
        if pre.is_dir() and link.is_symlink():
            link.unlink()
            pre.rename(link)
            restored = True
    return f"reverted {len(shas)} commit(s)" + (", silo restored" if restored else "")

