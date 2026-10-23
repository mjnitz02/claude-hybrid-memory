"""mem - audit and repair the Claude memory store, and run its hooks.

Enforces docs/format-spec.md.

    mem audit
    mem audit --scan legacy
    mem fix --write
    mem fresh --run
    mem hook session-start
    mem hook post-tool
    mem hook session-end
    mem events stats
    mem index [--rebuild]
    mem find <terms> [--territory T] [--all] [--superseded]
    mem show <slug> [--meta | --section H | --full] [--at REV]
    mem history <slug>
    mem supersede <old> <new>
    mem commit [-m SUBJECT]
    mem log [PATH...] [-n N]
    mem diff [PATH...] [--stat]
    mem restore PATH... [--from REV]
    mem audit --at REV
    mem render [TERRITORY] [--check]
    mem render TERRITORY --adopt [--write]
    mem install [--dry-run]
    mem migrate inventory [--source DIR ...]
    mem migrate summarize [--silo S ...] [--jobs N] [--model M] [--force] [--dry-run]
    mem migrate summaries [--silo S ...] [--json]
    mem migrate map [--rebuild] [--approve]
    mem migrate apply [--silo S ...] [--dry-run]
    mem migrate undo --silo S

Exit codes: 0 clean, 1 findings at error level, 2 tool error.
"""
from __future__ import annotations

import sys

HOOKS = ("session-start", "post-tool", "session-end")


def _hook(args: list[str], t0: float | None = None) -> int:
    """Run a hook. Never breaks a session: any failure exits 0 with nothing printed."""
    try:
        if args == ["session-start"]:
            from claude_hybrid_memory.hooks import session_start
            return session_start.main()
        if args == ["post-tool"]:
            from claude_hybrid_memory.hooks import post_tool
            return post_tool.main(t0)
        if args == ["session-end"]:
            from claude_hybrid_memory.hooks import session_end
            return session_end.main()
        print(f"mem hook: unknown event {' '.join(args)!r}; known: {', '.join(HOOKS)}",
              file=sys.stderr)
        return 0
    except Exception:
        return 0


def _run(argv: list[str]) -> int:
    import argparse
    import datetime as dt
    from pathlib import Path

    from claude_hybrid_memory.findings import report
    from claude_hybrid_memory.store import LEGACY, STORE, Memory, scan_legacy, scan_store

    ap = argparse.ArgumentParser(prog="mem", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["audit", "fix", "links", "fresh", "budget",
                                        "drift", "dup", "status", "link"])
    ap.add_argument("--territory", help="link: territory path, e.g. cards/archive-tools")
    ap.add_argument("--dir", type=Path, default=None,
                    help="link: the repo checkout to point at it (default: cwd)")
    ap.add_argument("--root", type=Path, default=STORE, help=f"store root (default {STORE})")
    ap.add_argument("--legacy", type=Path, default=LEGACY, help="legacy projects dir")
    ap.add_argument("--scan", choices=["store", "legacy", "both"], default="both")
    ap.add_argument("--run", action="store_true", help="fresh: actually execute verify recipes")
    ap.add_argument("--write", action="store_true", help="fix: apply changes")
    ap.add_argument("--stamp-today", action="store_true",
                    help="fix: set last_verified to today where absent. Only when the claims "
                         "were genuinely just verified; mtime is never used.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--at", metavar="REV",
                    help="check the store as it was at this commit (read-only commands)")
    a = ap.parse_args(argv)
    if a.at:
        return _run_at(a, argv)

    today = dt.date.today()
    mems: list[Memory] = []
    routers: dict = {}
    if a.scan in ("store", "both") and a.root.is_dir():
        m, r = scan_store(a.root)
        mems += m
        routers.update(r)
    if a.scan in ("legacy", "both"):
        m, r = scan_legacy(a.legacy)
        mems += m
        routers.update(r)

    if a.command == "link":
        if not a.territory:
            print("link requires --territory", file=sys.stderr)
            return 2
        from claude_hybrid_memory.silos import do_link
        return report(do_link(a.root, a.legacy, a.territory,
                              a.dir or Path.cwd(), a.write), a.json)

    if not mems:
        print(f"no memory files found (store={a.root}, legacy={a.legacy}, scan={a.scan})",
              file=sys.stderr)
        if a.json:
            print("[]")
        return 0

    from claude_hybrid_memory import audit

    c = a.command
    if c == "fix":
        from claude_hybrid_memory.fix import do_fix
        f = do_fix(mems, routers, a.write, a.stamp_today)
    elif c == "links":
        f = audit.check_links(mems, routers, audit.superseded_paths(a.root))
    elif c == "fresh":
        f = audit.check_freshness(mems, today, a.run)
    elif c == "budget":
        f = audit.check_budget(a.root, mems)
    elif c == "drift":
        f = (audit.check_router_drift(mems, routers, audit.superseded_paths(a.root))
             + audit.check_exports(a.root, routers))
    elif c == "dup":
        f = audit.check_dup(mems)
    elif c == "status":
        f = audit.check_silos(a.legacy, a.root)
    else:  # audit
        f = audit.run_all(mems, routers, a.root, a.legacy, today)
        hdr = (f"scanned {len(mems)} memory files, {len(routers)} routers "
               f"({sum(1 for m in mems if m.scope=='store')} store, "
               f"{sum(1 for m in mems if m.scope=='legacy')} legacy)")
        print(hdr, file=sys.stderr if a.json else sys.stdout)
    return report(f, a.json)


CACHE_COMMANDS = ("index", "find", "show", "history", "supersede")
GIT_COMMANDS = ("commit", "log", "diff", "restore")


def _render(argv: list[str]) -> int:
    """`mem render`: ALWAYS.md, and the generated MEMORIES section of each adopted index."""
    import argparse
    import json
    from pathlib import Path

    from claude_hybrid_memory import render
    from claude_hybrid_memory.findings import report
    from claude_hybrid_memory.store import STORE

    ap = argparse.ArgumentParser(prog="mem render")
    ap.add_argument("territory", nargs="?", help="one territory, e.g. console/tools")
    ap.add_argument("--root", type=Path, default=STORE, help=f"store root (default {STORE})")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="write nothing; flag stale renders and indexes past the line cap")
    mode.add_argument("--adopt", action="store_true",
                      help="migrate a hand-written index: a dry run unless --write")
    ap.add_argument("--write", action="store_true", help="adopt: apply it")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not (a.root / "territories").is_dir():
        print(f"no territories under {a.root}", file=sys.stderr)
        return 2
    if a.territory and not (a.root / "territories" / a.territory / "MEMORY.md").is_file():
        print(f"no territory {a.territory!r} (no MEMORY.md under territories/)", file=sys.stderr)
        return 2
    if a.write and not a.adopt:
        print("--write goes with --adopt; a plain `mem render` always writes", file=sys.stderr)
        return 2

    if a.check:
        return report(render.check(a.root, [a.territory] if a.territory else None), a.json)

    if a.adopt:
        if not a.territory:
            print("--adopt takes one territory", file=sys.stderr)
            return 2
        try:
            ad = render.adopt(a.root, a.territory)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        if a.write:
            n = render.write_adoption(a.root, ad)
            print(f"{a.territory}: rendered, {ad.before} -> {ad.after_lines} lines; "
                  f"`group:` written into {n} memories")
            return 0
        if a.json:
            keep = {k: v for k, v in ad.__dict__.items() if k not in ("after", "lines")}
            print(json.dumps({**keep,
                              "after_lines": ad.after_lines,
                              "lines": [ln.__dict__ for ln in ad.lines]}, indent=2))
            return 0
        _adoption_report(ad, render)
        return 0

    names = [a.territory] if a.territory else render.rendered(a.root)
    if a.territory and a.territory not in render.rendered(a.root):
        print(f"{a.territory} is not rendered yet; `mem render {a.territory} --adopt` first",
              file=sys.stderr)
        return 2
    from claude_hybrid_memory.audit.relations import store_graph
    from claude_hybrid_memory.hooks import session_start
    if not a.territory:
        changed = session_start.write_always(a.root)
        print(f"{session_start.ALWAYS}: {'re-rendered' if changed else 'unchanged'}")
    sup = store_graph(a.root).superseded()
    for n in names:
        old, new = render.render(a.root, n, True, sup)
        print(f"{n}: {'re-rendered' if old != new else 'unchanged'}, {new.count(chr(10))} lines")
    if not names:
        print("no territory is rendered yet; adopt one with `mem render <territory> --adopt`")
    return 0


def _adoption_report(ad, render) -> None:
    gap = [ln for ln in ad.lines if ln.missing]
    print(f"{ad.territory}: adoption dry run. Nothing is written; --write applies it.\n")
    mem = render.memory_lines(ad.after)
    over = mem - render.MEM_WARN
    print(f"Lines: {ad.before} now -> {ad.after_lines} rendered (harness cap {render.LINE_CAP}); "
          f"MEMORIES section {mem} (target {render.MEM_WARN}, cap {render.MEM_CAP})"
          + (f": {over} over target." if over > 0 else "."))
    if ad.after_lines > render.LINE_CAP:
        print(f"  The file is past the harness's {render.LINE_CAP} lines: "
              "the tail is never loaded.")
    if over > 0:
        print(f"  Each memory marked `tier: record` (or HISTORICAL) moves into its group's one "
              f"`{render.RECORDS}:` line,\n  so about {over} more such memories reach the target.")
    if ad.compact:
        print(f"  Already compact: {', '.join(ad.compact)}")
    print(f"\nGroups, in order ({len(ad.groups)}), written as `groups:` in MEMORY.md and "
          "`group:` on each memory:")
    for g in ad.groups:
        print(f"  {sum(1 for ln in ad.lines if ln.group == g):3d}  {g}")
    print("\nWithin a group, memories sort by slug; the hand-written order is not kept.")
    print(f"\nIndex lines saying something the description does not: {len(gap)} of "
          f"{len(ad.lines)}, most missing words first.\nThe rendered line is the "
          "description; fold in what matters, or let it go.\n")
    for ln in sorted(gap, key=lambda ln: (-len(ln.missing), ln.slug)):
        print(f"{ln.slug}  [{ln.group or render.OTHER}]")
        print(f"  index: [{ln.title}] {ln.gloss}")
        print(f"  desc:  {ln.description}")
        print(f"  missing: {', '.join(ln.missing)}\n")
    done = [ln.slug for ln in ad.lines if not ln.missing]
    if done:
        print(f"Already covered by the description ({len(done)}): {', '.join(done)}\n")
    for title, items in (("Prose in the section, which the render drops", ad.prose),
                         ("Index links to files that do not exist (dropped)", ad.ghosts),
                         ("Memories with no index line (rendered under their group:, "
                          f"else {render.OTHER})", ad.unlisted),
                         ("Superseded memories (dropped)", ad.superseded)):
        if items:
            print(f"{title}:")
            for x in items:
                print(f"  {x}")
            print()


def _install(argv: list[str]) -> int:
    """`mem install`: stand up or repair the store and its hooks (setup.md)."""
    import argparse
    from pathlib import Path

    from claude_hybrid_memory import install
    from claude_hybrid_memory.findings import report
    from claude_hybrid_memory.store import STORE

    ap = argparse.ArgumentParser(prog="mem install", description=install.__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change; write nothing")
    ap.add_argument("--root", type=Path, default=STORE, help=f"store root (default {STORE})")
    ap.add_argument("--repo", type=Path, default=install.REPO,
                    help=f"this repo, for templates/ and skills/ (default {install.REPO})")
    ap.add_argument("--claude-dir", type=Path, default=install.CLAUDE,
                    help=f"holds settings.json and skills/ (default {install.CLAUDE})")
    ap.add_argument("--mem", type=Path, default=install.MEM,
                    help=f"the binary the hooks run (default {install.MEM})")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not (a.repo / "templates").is_dir():
        print(f"{a.repo} has no templates/; pass --repo <claude-hybrid-memory checkout>",
              file=sys.stderr)
        return 2
    return report(install.run(a.root, a.repo, a.claude_dir, a.mem.absolute(), a.dry_run), a.json)


def _migrate(argv: list[str]) -> int:
    """`mem migrate`: fast adoption, docs/fast-adoption.md. Stages 1 and 2 so far."""
    import argparse
    import json
    from pathlib import Path

    from claude_hybrid_memory.migrate import inventory, summarize
    from claude_hybrid_memory.store import LEGACY, STORE

    ap = argparse.ArgumentParser(prog="mem migrate")
    ap.add_argument("stage", choices=["inventory", "summarize", "summaries", "map", "apply",
                                      "undo"])
    ap.add_argument("--root", type=Path, default=STORE, help=f"store root (default {STORE})")
    ap.add_argument("--legacy", type=Path, default=LEGACY, help="legacy projects dir")
    ap.add_argument("--source", type=Path, action="append",
                    help="a memory directory to adopt (default: every pending silo)")
    ap.add_argument("--silo", action="append", help="only silos whose name contains this")
    ap.add_argument("--jobs", type=int, default=summarize.JOBS, help="parallel processes")
    ap.add_argument("--model", default=summarize.MODEL)
    ap.add_argument("--force", action="store_true", help="re-summarize cached results too")
    ap.add_argument("--dry-run", action="store_true", help="summarize: say what would run")
    ap.add_argument("--rebuild", action="store_true",
                    help="map: redraft the plan; the old one is kept as plan.prev.yaml")
    ap.add_argument("--approve", action="store_true", help="map: approve the plan as it is")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.stage == "undo":
        return _undo(a)
    if a.stage == "apply":
        return _apply(a)
    sources = [s.expanduser().resolve() for s in a.source] if a.source \
        else inventory.pending_silos(a.legacy)
    inv = inventory.build(a.root, sources)
    out = inventory.write(a.root, inv)
    if a.stage == "inventory":
        if a.json:
            print(json.dumps(inv, indent=1, ensure_ascii=False))
            return 0
        for s in inv["silos"]:
            fs = [f for f in inv["files"] if f["silo"] == s["silo"]]
            flags = [f"{n} {k}" for k, n in (
                ("mention other repos", sum(1 for f in fs if f["repos"])),
                ("near-duplicates", sum(1 for f in fs if f["duplicates"])),
                ("live claims", sum(1 for f in fs if f["live_claims"])),
                ("split candidates", sum(1 for f in fs if f["split_candidate"]))) if n]
            print(f"{s['repo'] or s['silo']}: {len(fs)} files"
                  + ("" if s["workdir"] else ", not on this disk")
                  + (f", MIXED STATE {s['mixed_state']}" if s["mixed_state"] else "")
                  + (f"; {', '.join(flags)}" if flags else ""))
        print(f"\n{len(inv['silos'])} silos, {len(inv['files'])} files -> {out}")
        return 0

    router = (a.root / "ROUTER.md").read_text(encoding="utf-8") \
        if (a.root / "ROUTER.md").is_file() else ""
    jobs = summarize.jobs_for(inv, router, a.silo)
    if not jobs:
        print("nothing to summarize", file=sys.stderr)
        return 2
    have = summarize.cached(a.root, jobs, a.model)
    if a.stage == "summaries":
        return _summaries(jobs, have, a.json)
    if a.stage == "map":
        return _map(a, inv, have, router)
    todo = [j for j in jobs if a.force or have.get(j.id, {}).get("status") != "ok"]
    if a.dry_run:
        print(f"{len(todo)} to run, {len(jobs) - len(todo)} cached, model {a.model}, "
              f"about ${0.02 * len(todo):.2f}")
        for j in todo:
            print(f"  {j.kind:4}  {j.id}")
        return 0

    def progress(n, total, r):
        how = ("cached" if r["cached"]
               else f"{r.get('ms', 0) / 1000:.1f}s ${r.get('cost_usd', 0):.3f}")
        err = f"  {r.get('error', '')[:100]}" if r["status"] != "ok" else ""
        print(f"[{n}/{total}] {r['status']:6} {r['id'][-60:]}  {how}{err}", file=sys.stderr)

    res = summarize.run(a.root, jobs, a.model, a.jobs, a.force, progress)
    ran = [r for r in res if not r["cached"]]
    failed = [r for r in res if r["status"] != "ok"]
    print(f"{len(res)} summaries: {len(ran)} run, {len(res) - len(ran)} cached, "
          f"{len(failed)} failed; ${sum(r.get('cost_usd', 0) for r in ran):.2f}, "
          f"{sum(r.get('tokens_in', 0) for r in ran):,} tokens in, "
          f"{sum(r.get('tokens_out', 0) for r in ran):,} out")
    return 1 if failed else 0


def _map(a, inv: dict, have: dict, router: str) -> int:
    """`mem migrate map`: draft, check and approve the territory map (fast-adoption §6)."""
    import json

    from claude_hybrid_memory.migrate import plan as P

    plan = P.load(a.root)
    if plan is None or a.rebuild:
        if plan is not None:
            P.path(a.root).replace(P.path(a.root).with_name("plan.prev.yaml"))
        plan = P.draft(a.root, inv, have, router)
        P.write(a.root, plan)
        print(f"drafted {P.path(a.root)}")
    errs = P.check(plan, inv, a.root)
    if a.approve and not errs:
        plan = P.approve(plan)
        P.write(a.root, plan)
    if a.json:
        print(json.dumps({"plan": plan, "problems": errs, "approved": P.is_approved(plan)},
                         indent=1, ensure_ascii=False))
        return 1 if errs else 0
    print("\n".join(P.table(plan, inv)))
    for e in errs:
        print(f"PROBLEM  {e}")
    if errs:
        print(f"\n{len(errs)} problem(s) to fix in {P.path(a.root)} before approving")
        return 1
    if P.is_approved(plan):
        print(f"\napproved {plan['approved']['at']}; stage 4 may land it")
    elif plan.get("approved"):
        print("\nedited since it was approved: review, then mem migrate map --approve")
    else:
        print(f"\nnot approved. Review {P.path(a.root)}, then mem migrate map --approve")
    return 0


def _apply(a) -> int:
    """`mem migrate apply`: land the approved plan (fast-adoption §7)."""
    from claude_hybrid_memory.migrate import apply, inventory
    from claude_hybrid_memory.migrate import plan as P

    plan = P.load(a.root)
    if plan is None:
        print("no plan: mem migrate map", file=sys.stderr)
        return 2
    # the plan was drawn up against the silos as they were; landed ones are no longer
    # pending, so the inventory it is checked against includes every silo it names
    names = {s["silo"] for s in plan["silos"]}
    sources = [d / "memory.premigration" if (d / "memory").is_symlink() else d / "memory"
               for d in (a.legacy / n for n in sorted(names))]
    inv = inventory.build(a.root, [s for s in sources if s.is_dir()])

    def progress(silo, rec):
        print(f"landed {silo} -> {rec['territory']}: {rec['files']} files, commits "
              f"{', '.join(rec['commits'])}")
        for n in rec["notes"]:
            print(f"   {n}")

    out, errs = apply.run(a.root, plan, inv, a.legacy, a.silo, a.dry_run, progress)
    if a.dry_run:
        for la in out:
            print(f"{la['silo']} -> {la['territory']}")
            for file, slug, action in la["files"]:
                print(f"   {action:8} {file} -> {slug}.md")
    for e in errs:
        print(f"STOP  {e}", file=sys.stderr)
    if not errs and not a.dry_run:
        print(f"\n{len(out)} silo(s) landed; mem status should show them migrated")
    return 1 if errs else 0


def _undo(a) -> int:
    from claude_hybrid_memory.migrate import apply

    log = apply.applied(a.root)
    hits = [s for s in log if a.silo and any(x in s for x in a.silo)]
    if len(hits) != 1:
        print(f"name exactly one landed silo with --silo; matches: {hits or 'none'}",
              file=sys.stderr)
        return 2
    try:
        print(f"{hits[0]}: {apply.undo(a.root, hits[0], a.legacy)}")
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


def _summaries(jobs, have: dict, as_json: bool) -> int:
    """The compact table stage 3 reads: one line per silo, one per file."""
    import json

    if as_json:
        print(json.dumps([have.get(j.id, {"id": j.id, "kind": j.kind, "status": "missing"})
                          for j in jobs], indent=1, ensure_ascii=False))
        return 0
    # jobs run silos first; the table reads silo by silo
    rank = {j.id: i for i, j in enumerate(jobs) if j.kind == "silo"}
    for j in sorted(jobs, key=lambda j: (rank.get(j.id.rsplit("/", 1)[0] if j.kind == "file"
                                                  else j.id, 0), j.kind != "silo")):
        r = have.get(j.id)
        s = (r or {}).get("summary")
        if j.kind == "silo":
            print(f"\n## {j.id}")
            if s:
                home = s["territory_existing"] or f"NEW {s['territory_new']}"
                print(f"   -> {home}  ({s['mode']}, {s['confidence']})  {s['subject']}")
                print(f"   {s['summary']}")
            continue
        name = j.id.rsplit("/", 1)[-1]
        if not s:
            print(f"   {name}: {(r or {}).get('status', 'missing')}")
            continue
        tags = [s["description_verdict"], s["kind"], *s["shape"]]
        if s["verify"]:
            tags.append(f"verify x{len(s['verify'])}")
        if s["territory_hint"]:
            tags.append(f"-> {s['territory_hint']}")
        if s["obsolete"]["likely"]:
            tags.append("OBSOLETE?")
        if s["confidence"] != "high":
            tags.append(f"{s['confidence']} confidence")
        print(f"   {name}  [{', '.join(tags)}]\n      {s['conclusion']}")
    missing = sum(1 for j in jobs if (have.get(j.id) or {}).get("status") != "ok")
    if missing:
        print(f"\n{missing} of {len(jobs)} not summarized yet: mem migrate summarize")
    return 0


def _storegit(argv: list[str]) -> int:
    """`mem commit | log | diff | restore`: git on the store, and only the store
    (direction §16.1)."""
    import argparse
    import json
    import os
    from pathlib import Path

    from claude_hybrid_memory import storegit
    from claude_hybrid_memory.store import STORE

    cmd, rest = argv[0], argv[1:]
    ap = argparse.ArgumentParser(prog=f"mem {cmd}")
    ap.add_argument("--root", type=Path, default=STORE, help=f"store root (default {STORE})")
    if cmd == "commit":
        ap.add_argument("-m", dest="subject", help="subject line; the body is still generated")
        ap.add_argument("--json", action="store_true")
    elif cmd == "restore":
        ap.add_argument("paths", nargs="+", help="files or directories, store-relative or absolute")
        ap.add_argument("--from", dest="rev", default="HEAD", help="commit to restore from")
        ap.add_argument("--json", action="store_true")
    else:
        ap.add_argument("paths", nargs="*", help="store-relative or absolute paths")
        if cmd == "log":
            ap.add_argument("-n", type=int, default=20)
        else:
            ap.add_argument("--stat", action="store_true")
    a = ap.parse_args(rest)
    root = Path(os.path.realpath(a.root))
    if not storegit.is_repo(root):
        print(f"{root} is not a git repository (setup.md step 1b)", file=sys.stderr)
        return 2

    if cmd == "commit":
        r = storegit.commit(root, "mem commit", os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                            a.subject)
        if a.json:
            print(json.dumps(r.__dict__))
        else:
            print(f"{r.sha}  {r.detail}" if r.sha else f"{r.status}: {r.detail}")
        return 0 if r.status in ("committed", "clean") else 1
    paths = [os.path.relpath(os.path.realpath(p), root) if os.path.isabs(p) else p
             for p in a.paths]
    if cmd == "restore":
        r = storegit.restore(root, paths, a.rev)
        if a.json:
            print(json.dumps(r.__dict__))
        elif r.status != "restored":
            print(f"nothing restored: {r.detail}", file=sys.stderr)
        else:
            if r.snapshot:
                print(f"{r.snapshot}  committed first, so what this overwrote stays in history")
            for f in r.changed:
                print(f"restored   {f}")
            for f in r.unchanged:
                print(f"unchanged  {f}")
        return 0 if r.status == "restored" else 1
    if cmd == "log":
        return storegit.passthrough(root, "log", f"-n{a.n}", "--date=short",
                                    "--format=%ad  %h  %s", "--", *paths)
    rc = storegit.passthrough(root, "diff", "HEAD", *(["--stat"] if a.stat else []),
                              "--", *paths)
    new = storegit.untracked(root, paths)
    if new:
        print(f"\n{len(new)} untracked (new) file{'s' if len(new) != 1 else ''}:")
        for p in new:
            print(f"  {p}")
    return rc


def _events(argv: list[str]) -> int:
    """`mem events stats`: what the event log holds, and the hook's own cost."""
    import argparse
    import json
    import statistics
    from collections import Counter
    from pathlib import Path

    from claude_hybrid_memory import events
    from claude_hybrid_memory.store import STORE

    ap = argparse.ArgumentParser(prog="mem events")
    ap.add_argument("action", choices=["stats"])
    ap.add_argument("--root", type=Path, default=STORE)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    evs = list(events.read_all(a.root))
    kinds = Counter(e.get("event") for e in evs)
    tools = Counter(e.get("tool") for e in evs)
    ms = sorted(e["ms"] for e in evs if isinstance(e.get("ms"), (int, float)))
    first = evs[0]["ts"] if evs else None
    out = {"events": len(evs), "by_kind": dict(kinds), "by_tool": dict(tools),
           "git_writes": events.git_writes(a.root, first),
           "first": evs[0]["ts"] if evs else None, "last": evs[-1]["ts"] if evs else None,
           "sessions": len({e.get("session") for e in evs}),
           "ms_p50": statistics.median(ms) if ms else None,
           "ms_p95": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else None,
           "top_read": events.read_counts(a.root).most_common(10)}
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"{out['events']} events ({', '.join(f'{n} {k}' for k, n in kinds.items()) or 'none'}) "
          f"from {out['sessions']} sessions, {out['first']} .. {out['last']}")
    if tools:
        print(f"by tool: {', '.join(f'{n} {k}' for k, n in tools.most_common())}")
    gw = out["git_writes"]
    if gw:
        print(f"writes from store git since then: {gw['changes']} file changes, "
              f"{gw['files']} distinct files, in {gw['commits']} commits")
    if ms:
        print(f"hook in-process time: p50 {out['ms_p50']:.1f} ms, p95 {out['ms_p95']:.1f} ms "
              "(plus ~10 ms interpreter start, not visible from inside)")
    for path, n in out["top_read"]:
        print(f"  {n:4d}  {path}")
    return 0


def _cache(argv: list[str]) -> int:
    """`mem index | find | show | history | supersede`: the derived cache."""
    import argparse
    import json
    from pathlib import Path

    from claude_hybrid_memory import cache
    from claude_hybrid_memory.store import STORE

    cmd, rest = argv[0], argv[1:]
    ap = argparse.ArgumentParser(prog=f"mem {cmd}")
    ap.add_argument("--root", type=Path, default=STORE, help=f"store root (default {STORE})")
    ap.add_argument("--json", action="store_true")
    if cmd == "index":
        ap.add_argument("--rebuild", action="store_true", help="drop and rebuild every row")
    elif cmd == "find":
        ap.add_argument("terms", nargs="+", help="each argument is one phrase; all must match")
        ap.add_argument("--territory", help="only this territory and those under it")
        ap.add_argument("--all", action="store_true", help="include archive/")
        ap.add_argument("--superseded", action="store_true",
                        help="include memories a newer one supersedes")
        ap.add_argument("--limit", type=int, default=10)
    elif cmd == "supersede":
        ap.add_argument("old", help="the memory being replaced")
        ap.add_argument("new", help="the memory replacing it; gets the `supersedes:` line")
    elif cmd == "history":
        ap.add_argument("spec", help="slug, territory/slug, or a store-relative path")
    else:
        ap.add_argument("spec", help="slug, territory/slug, or a store-relative path")
        part = ap.add_mutually_exclusive_group()
        part.add_argument("--meta", action="store_true", help="frontmatter and outline")
        part.add_argument("--section", metavar="HEADING",
                          help="one section (exact, else substring)")
        part.add_argument("--full", action="store_true", help="the whole file")
        ap.add_argument("--at", metavar="REV", help="the file as it was at this store commit")
    a = ap.parse_args(rest)
    if not a.root.is_dir():
        print(f"no store at {a.root}", file=sys.stderr)
        return 2

    conn = cache.connect(a.root, fresh=cmd == "index" and a.rebuild)
    st = cache.refresh(conn, a.root)

    if cmd == "index":
        if a.json:
            print(json.dumps(st.__dict__))
        else:
            areas = ", ".join(f"{n} {k}" for k, n in sorted(st.by_area.items()))
            print(f"{st.files} files ({areas}), {st.sections} sections in {st.ms:.0f} ms: "
                  f"{st.added} added, {st.updated} updated, {st.removed} removed, "
                  f"{st.touched} touched, {st.unchanged} unchanged")
        return 0

    if cmd == "find":
        found = cache.find(conn, a.terms, a.territory, a.all, a.superseded, a.limit)
        _log(a.root, "search", a.territory or "", "mem find", query=a.terms,
             hits=[h.path for h in found.hits])
        if a.json:
            print(json.dumps({"hits": [h.__dict__ for h in found.hits],
                              "archive_hidden": found.archive_hidden,
                              "superseded_hidden": found.superseded_hidden,
                              "partial": found.partial}, indent=2))
            return 0
        if found.partial:
            print("No memory has every term; showing memories with any of them.\n")
        for h in found.hits:
            head = " · ".join(x for x in (h.container, h.slug, h.status, h.tier,
                                          h.last_verified and f"verified {h.last_verified}") if x)
            print(head)
            if h.superseded_by:
                print(f"  SUPERSEDED by {', '.join(h.superseded_by)}")
            if h.description:
                d = h.description
                print("  " + (d if len(d) <= 220 else d[:217] + "..."))
            line = h.sections[0][1] if h.sections else 1
            secs = " · ".join(dict.fromkeys(s for s, _ in h.sections[:3]))
            print(f"  {a.root / h.path}:{line}" + (f"  § {secs}" if secs else ""))
        if not found.hits:
            print("no matches")
        if found.archive_hidden or found.superseded_hidden:
            print()
        for n, where, flag in ((found.archive_hidden, "in archive/", "--all"),
                               (found.superseded_hidden, "superseded", "--superseded")):
            if n:
                print(f"{n} match{'es' if n != 1 else ''} {where} not shown ({flag})")
        return 0

    if cmd == "supersede":
        return _supersede(conn, a.root, a.old, a.new)
    if cmd == "show" and a.at:
        return _show_at(conn, a)
    one = _resolve_one(conn, a.spec)
    if one is None:
        return 2
    path, container, slug = one
    if cmd == "history":
        return _history(conn, a.root, path, a.json)
    p = a.root / path
    if cmd == "show":
        _log(a.root, "read", path, "mem show")
    fid = conn.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()[0]
    newer = cache.superseded_by(conn, fid)
    text = p.read_text(encoding="utf-8", errors="replace")
    return _show_text(a, text, p, container, slug, newer)


def _show_text(a, text: str, p, container: str, slug: str, newer: list[str]) -> int:
    import json

    from claude_hybrid_memory import cache

    if a.full:
        print(text, end="" if text.endswith("\n") else "\n")
        return 0
    if a.section:
        cands, body = cache.section_text(text, a.section)
        if not body:
            msg = "matches several sections" if cands else "matches no section"
            print(f"{a.section!r} {msg} in {container}/{slug}; headings:", file=sys.stderr)
            for s in cands or cache.sections_of(text):
                if s.heading:
                    print(f"  {'#' * s.level} {s.heading}", file=sys.stderr)
            return 2
        print(f"{p}:{cands[0].line}\n\n{body}")
        return 0
    from claude_hybrid_memory.store import parse_frontmatter
    meta, _, _ = parse_frontmatter(text)
    if a.json:
        print(json.dumps({"path": str(p), "container": container, "slug": slug, "meta": meta,
                          "superseded_by": newer,
                          "outline": [{"level": s.level, "heading": s.heading, "line": s.line}
                                      for s in cache.sections_of(text) if s.heading]},
                         default=str, indent=2))
        return 0
    print(f"{container}/{slug}  {p}")
    if newer:
        print(f"SUPERSEDED by {', '.join(newer)}; `mem history {slug}` for the chain")
    if a.meta:
        for k, v in meta.items():
            if k == "metadata" and isinstance(v, dict):
                continue  # its keys are hoisted to the top level and print there
            print(f"  {k}: {v}")
        print(f"  ({len(text.encode())} bytes, {text.count(chr(10))} lines)")
        for s in cache.sections_of(text):
            if s.heading:
                print(f"  {'  ' * (s.level - 1)}{s.heading}  :{s.line}")
        return 0
    desc = str(meta.get("description") or "").strip()
    if desc:
        print(f"\n{desc}")
    para = cache.opening_paragraph(text)
    if para:
        print(f"\n{para}")
    return 0


def _show_at(conn, a) -> int:
    """`mem show --at REV`: a memory, or any store file, as that commit had it. The spec
    resolves against today's memories first, then as a store-relative path, so a file
    since deleted or renamed is still reachable by its old path."""
    import os
    from pathlib import Path

    from claude_hybrid_memory import cache, storegit

    root = Path(os.path.realpath(a.root))
    if not storegit.is_repo(root):
        print(f"{root} is not a git repository (setup.md step 1b)", file=sys.stderr)
        return 2
    sha = storegit.resolve(root, a.at)
    if not sha:
        print(f"{a.at!r} names no commit in the store", file=sys.stderr)
        return 2
    rows = cache.resolve(conn, a.spec)
    if len(rows) == 1:
        path, container, slug = rows[0]
    else:
        path = os.path.relpath(os.path.realpath(a.spec), root) if os.path.isabs(a.spec) else a.spec
        path = storegit.locate(root, sha, path)
        container, slug = os.path.dirname(path).removeprefix("territories/"), Path(path).stem
    data = storegit.read_at(root, sha, path)
    if data is None:
        print(f"{path} did not exist at {a.at}", file=sys.stderr)
        return 2
    return _show_text(a, data.decode("utf-8", errors="replace"), f"{a.at}:{path}",
                      container, slug, [])


def _log(root, event: str, path: str, tool: str, **extra) -> None:
    """A usage event from `mem` itself. It runs from Bash, which the PostToolUse hook
    skips for `mem` commands, so without this its reads would be invisible."""
    import os

    from claude_hybrid_memory import events

    try:
        events.append(root, {"event": event, "path": path, "tool": tool,
                             "session": os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                             "cwd": os.getcwd(), **extra})
    except OSError:
        pass


def _resolve_one(conn, spec: str):
    """(path, container, slug) for exactly one memory, else say why on stderr."""
    from claude_hybrid_memory import cache

    rows = cache.resolve(conn, spec)
    if len(rows) == 1:
        return rows[0]
    if rows:
        print(f"{spec!r} is ambiguous; name one:", file=sys.stderr)
        for _, container, slug in rows:
            print(f"  {container}/{slug}", file=sys.stderr)
    else:
        print(f"no memory {spec!r}; try `mem find {spec}`", file=sys.stderr)
    return None


def _history(conn, root, path: str, as_json: bool) -> int:
    """`mem history`: the version chain in both directions, then git's log of the file."""
    import json

    from claude_hybrid_memory import cache, chains, storegit

    g = cache.graph(conn)
    info = dict(((p, (st, d)) for p, st, d in conn.execute(
        "SELECT path, status, description FROM files")))
    older, newer = chains.walk(g, path, "older"), chains.walk(g, path, "newer")
    log = storegit.file_log(root, path)

    def row(depth, node, note):
        if node is None:
            return {"depth": depth, "ref": note}
        st, desc = info.get(node.path, ("", ""))
        return {"depth": depth, "key": node.key, "path": node.path, "area": node.area,
                "status": st, "description": desc, "note": note}

    me = g.nodes[path]
    if as_json:
        print(json.dumps({"key": me.key, "path": path,
                          "superseded": path in g.superseded(),
                          "older": [row(*x) for x in older], "newer": [row(*x) for x in newer],
                          "commits": [dict(zip(("date", "commit", "subject"), c, strict=False))
                                      for c in log] if log is not None else None}, indent=2))
        return 0
    print(f"{me.key}  {root / path}")
    print("  SUPERSEDED" if path in g.superseded() else "  current: nothing supersedes it")

    def show(title, walked, empty):
        print(f"\n{title}")
        if not walked:
            print(f"  {empty}")
        for x in walked:
            r = row(*x)
            pad = "  " * r["depth"]
            if "ref" in r:
                print(f"{pad}{r['ref']}")
                continue
            tags = " · ".join(t for t in (r["status"], "archive" if r["area"] == "archive"
                                          else "", r["note"]) if t)
            print(f"{pad}{r['key']}" + (f"  [{tags}]" if tags else ""))
            if r["description"]:
                d = r["description"]
                print(f"{pad}  {d if len(d) <= 160 else d[:157] + '...'}")

    show("Supersedes (older):", older, "nothing")
    show("Superseded by (newer):", newer, "nothing")
    print("\nCommits touching this file:")
    if log is None:
        print("  (no git history: the store is not a repository, or git failed)")
    for date, commit, subject in log or []:
        print(f"  {date}  {commit}  {subject}")
    if log == []:
        print("  none yet (uncommitted)")
    return 0


def _supersede(conn, root, old_spec: str, new_spec: str) -> int:
    """`mem supersede <old> <new>`: write `supersedes:` into <new>. <old> is never touched.

    Mechanical help only: deciding that <new> replaces <old>, and writing <new>, are the
    session's job."""
    import os

    from claude_hybrid_memory import cache, chains
    from claude_hybrid_memory.spec import INDEX_LINK_RE

    old, new = _resolve_one(conn, old_spec), _resolve_one(conn, new_spec)
    if old is None or new is None:
        return 2
    g = cache.graph(conn)
    o, n = g.nodes[old[0]], g.nodes[new[0]]
    if o.path == n.path:
        print("a memory cannot supersede itself", file=sys.stderr)
        return 2
    if n.area == "archive":
        print(f"{n.key} is in archive/; a retired memory supersedes nothing", file=sys.stderr)
        return 2
    if o.path in g.older.get(n.path, []):
        print(f"{n.key} already supersedes {o.key}")
        return 0
    if any(x and x.path == n.path for _, x, _ in chains.walk(g, o.path, "older")):
        print(f"refused: {o.key} already supersedes {n.key} (directly or through a chain); "
              "this would make a loop", file=sys.stderr)
        return 2
    p = root / n.path
    text = p.read_text(encoding="utf-8")
    if not text.startswith("---") or text.find("\n---", 3) == -1:
        print(f"{p} has no frontmatter to add `supersedes:` to", file=sys.stderr)
        return 2
    unique = len(chains.lookup(list(g.nodes.values()), o.slug, n.container)) == 1
    p.write_text(chains.with_refs(text, [*n.refs, o.slug if unique else o.key]),
                 encoding="utf-8")
    # The PostToolUse hook skips `mem` commands, so this one logs itself.
    _log(root, "write", n.path, "mem supersede")
    cache.refresh(conn, root)
    print(f"{n.key} now supersedes {o.key}; {o.key} is unchanged on disk and drops out of "
          "default search")
    others = [s.key for s in g.successors(o.path) if s.path != n.path]
    if others:
        print(f"note: {o.key} is also superseded by {', '.join(others)}")
    r = root / "territories" / o.container / "MEMORY.md"
    if o.area == "territory" and r.is_file() and any(
            os.path.basename(t) == os.path.basename(o.path)
            for t in INDEX_LINK_RE.findall(r.read_text(encoding="utf-8", errors="replace"))):
        print(f"{r} still lists {os.path.basename(o.path)}; drop that line so the index "
              f"routes to {n.key}")
    return 0


def _run_at(a, argv: list[str]) -> int:
    """`mem audit --at REV`: the same command over the store's tree at REV, exported to a
    temporary directory outside the store. Paths in the report name the live store, so a
    before and after compare line for line."""
    import contextlib
    import io
    import os
    import tempfile
    from pathlib import Path

    from claude_hybrid_memory import storegit

    if a.command in ("fix", "link", "status"):
        print(f"--at is for read-only checks; `mem {a.command}` acts on the live store",
              file=sys.stderr)
        return 2
    root = Path(os.path.realpath(a.root))
    if not storegit.is_repo(root):
        print(f"{root} is not a git repository (setup.md step 1b)", file=sys.stderr)
        return 2
    sha = storegit.resolve(root, a.at)
    if not sha:
        print(f"{a.at!r} names no commit in the store", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="mem-at-") as tmp:
        tmp = os.path.realpath(tmp)
        storegit.export(root, sha, Path(tmp))
        rest, skip = [], False
        for x in argv:
            if skip:
                skip = False
            elif x in ("--at", "--root"):
                skip = True
            elif not x.startswith(("--at=", "--root=")):
                rest.append(x)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _run(rest + ["--root", tmp])
    out = buf.getvalue().replace(tmp, str(root))
    if not a.json:
        out = f"{root} at {a.at} ({sha[:7]})\n" + out
    print(out, end="")
    return rc


def main(argv: list[str] | None = None) -> int:
    import time
    t0 = time.perf_counter()
    args = sys.argv[1:] if argv is None else argv
    # The hook path runs at the start of every session, so it is dispatched before argparse
    # or any audit module is imported. tests/test_import_discipline.py holds that line.
    if args[:1] == ["hook"]:
        return _hook(args[1:], t0)
    try:
        if args[:1] and args[0] in CACHE_COMMANDS:
            return _cache(args)
        if args[:1] == ["events"]:
            return _events(args[1:])
        if args[:1] and args[0] in GIT_COMMANDS:
            return _storegit(args)
        if args[:1] == ["render"]:
            return _render(args[1:])
        if args[:1] == ["install"]:
            return _install(args[1:])
        if args[:1] == ["migrate"]:
            return _migrate(args[1:])
        return _run(args)
    except KeyboardInterrupt:
        return 130
