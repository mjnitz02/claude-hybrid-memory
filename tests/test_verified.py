"""`last_verified:` stamping and `mem backfill-verified` (verify-on-use, docs/direction.md)."""

from __future__ import annotations

import datetime as dt
import os
import subprocess

from conftest import Fixture, mem_cmd, run

from claude_hybrid_memory import verified
from claude_hybrid_memory.store import parse_frontmatter, scan_store

D = dt.date(2026, 9, 11)


def git(root, *args, date: str | None = None) -> str:
    env = {**os.environ, **({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {})}
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, env=env
    ).stdout


def init(root) -> None:
    """A store whose history starts at a baseline commit, as the real one does: every file
    in it predates the history, so the baseline's date is not their landing date."""
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / ".gitignore").write_text(".cache/\nALWAYS.md\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Baseline", date="2026-10-21T12:00:00")


def undated(root) -> dict[str, str]:
    """Store-relative path -> territory of every memory backfill should consider."""
    from claude_hybrid_memory.audit import superseded_paths

    sup = superseded_paths(root)
    return {
        str(m.path.relative_to(root)): m.container
        for m in scan_store(root)[0]
        if m.path not in sup
        and m.last_verified is None
        and str(m.meta.get("tier") or "") != "record"
    }


def test_stamp_sets_a_top_level_field_and_reads_back():
    nested = (
        "---\nname: a\ndescription: d\nmetadata:\n  type: project\n  modified: x\n---\n"
        "\nBody with last_verified: in prose.\n"
    )
    out = verified.stamp(nested, D)
    assert out is not None
    meta, body, problems = parse_frontmatter(out)
    assert not problems and str(meta["last_verified"]) == "2026-09-11"
    assert meta["metadata"] == {"type": "project", "modified": "x"}
    assert body.strip() == "Body with last_verified: in prose."  # the body is untouched

    again = verified.stamp(out, dt.date(2026, 11, 3))  # replaces, never doubles
    assert again is not None
    assert again.count("last_verified:") == 2  # one field, one in prose
    assert str(parse_frontmatter(again)[0]["last_verified"]) == "2026-11-03"

    assert verified.stamp("no frontmatter\n", D) is None


def test_backfill_refuses_baseline_files_without_a_date(fx: Fixture):
    init(fx.store)
    p = verified.plan(fx.store, {})
    want = undated(fx.store)
    assert want and not p.stamps  # all of it predates history
    assert {f for fs in p.baseline.values() for f in fs} == set(want)


def test_backfill_uses_landing_commits_and_baseline_dates(fx: Fixture):
    init(fx.store)
    kit = fx.store / "territories/console/kit"
    (kit / "kit-landed-later.md").write_text(
        "---\nname: kit-landed-later\ndescription: d\nkind: territory\n---\n\nBody.\n"
    )
    (kit / "kit-a-record.md").write_text(
        "---\nname: kit-a-record\ndescription: d\nkind: territory\ntier: record\n---\n\nB.\n"
    )
    git(fx.store, "add", "-A")
    git(fx.store, "commit", "-q", "-m", "landed", date="2026-10-29T12:00:00")

    terrs = set(undated(fx.store).values())
    p = verified.plan(fx.store, {t: D for t in terrs})
    assert not p.baseline and not p.bad_dates
    by = {s.rel: s for s in p.stamps}
    late = by.pop("territories/console/kit/kit-landed-later.md")
    assert late.date == dt.date(2026, 10, 29) and late.source.startswith("landed ")
    assert "territories/console/kit/kit-a-record.md" not in by  # records have no date
    assert by and all(s.date == D and s.source == "baseline" for s in by.values())


def test_backfill_refuses_unusable_dates(fx: Fixture):
    init(fx.store)
    terrs = set(undated(fx.store).values())
    t = sorted(terrs)[0]
    p = verified.plan(fx.store, {**{x: D for x in terrs}, t: dt.date(2026, 10, 25), "no/such": D})
    assert any(b.startswith(f"{t}=2026-10-25: after the baseline") for b in p.bad_dates)
    assert any(b.startswith("no/such:") for b in p.bad_dates)


def test_backfill_cli_dry_runs_then_writes_one_commit(fx: Fixture):
    init(fx.store)
    want = undated(fx.store)
    flags = [x for t in sorted(set(want.values())) for x in ("--baseline-date", f"{t}={D}")]
    base = ["--root", str(fx.store)]
    env = fx.env()

    rc, out, err = run(mem_cmd("backfill-verified", *base), env)  # no dates: refuses
    assert rc == 1 and "Nothing written" in out, out + err

    before = git(fx.store, "rev-parse", "HEAD")
    rc, out, err = run(mem_cmd("backfill-verified", *flags, *base), env)
    assert rc == 0 and "Dry run" in out, out + err
    assert git(fx.store, "rev-parse", "HEAD") == before and undated(fx.store) == want

    rc, out, err = run(mem_cmd("backfill-verified", *flags, "--write", *base), env)
    assert rc == 0 and "committed" in out, out + err
    assert undated(fx.store) == {}
    for rel in want:
        assert str(parse_frontmatter((fx.store / rel).read_text())[0]["last_verified"]) == str(D)
    assert git(fx.store, "rev-list", "--count", "HEAD").strip() == "2"
    assert not git(fx.store, "status", "--porcelain").strip()


def test_backfill_cli_will_not_write_over_uncommitted_changes(fx: Fixture):
    init(fx.store)
    (fx.store / "territories/console/kit/MEMORY.md").write_text("changed\n")
    flags = [
        x for t in sorted(set(undated(fx.store).values())) for x in ("--baseline-date", f"{t}={D}")
    ]
    rc, _, err = run(
        mem_cmd("backfill-verified", *flags, "--write", "--root", str(fx.store)), fx.env()
    )
    assert rc == 2 and "uncommitted" in err


def verified_cmd(fx: Fixture, *args: str):
    return run(mem_cmd("verified", *args, "--root", str(fx.store)), fx.env())


def test_verified_stamps_today_and_logs_the_note(fx: Fixture):
    import json

    rel = "territories/console/kit/kit-unlisted-orphan.md"
    rc, out, err = verified_cmd(fx, "kit-unlisted-orphan", "-m", "  the  card is still there ")
    assert rc == 0, err
    today = dt.date.today().isoformat()
    assert f"last_verified {today}" in out
    assert str(parse_frontmatter((fx.store / rel).read_text())[0]["last_verified"]) == today
    evs = [
        json.loads(ln)
        for f in sorted((fx.store / "events").glob("*.jsonl"))
        for ln in f.read_text().splitlines()
    ]
    v = [e for e in evs if e["event"] == "verified"]
    assert len(v) == 1 and v[0]["path"] == rel and v[0]["note"] == "the card is still there"


def test_verified_refuses_records_superseded_and_an_empty_note(fx: Fixture):
    kit = fx.store / "territories/console/kit"
    (kit / "kit-a-record.md").write_text(
        "---\nname: kit-a-record\ndescription: d\nkind: territory\ntier: record\n---\n\nB.\n"
    )
    for args, why in [
        (("kit-a-record", "-m", "x"), "record"),
        (("kit-sync-v1", "-m", "x"), "superseded"),
        (("kit-unlisted-orphan", "-m", "  "), "empty"),
        (("no-such-memory", "-m", "x"), "no memory"),
    ]:
        rc, _, err = verified_cmd(fx, *args)
        assert rc == 2 and why in err, (args, err)
    assert "last_verified" not in (kit / "kit-a-record.md").read_text()


def test_no_split_writes_a_ceiling_and_refuses_what_is_never_asked(fx: Fixture):
    t = fx.store / "territories/console/kit"
    p = t / "kit-long-argument.md"
    p.write_text(
        "---\nname: kit-long-argument\nkind: territory\ndescription: big\n---\n\n" + "y" * 15000
    )
    rc, out, err = run(
        mem_cmd(
            "no-split", "kit-long-argument", "-m", "one argument: keep it", "--root", str(fx.store)
        ),
        fx.env(),
    )
    assert rc == 0, err
    meta = parse_frontmatter(p.read_text())[0]
    assert meta["splittable"] == "no until 20 KB: one argument: keep it"
    p.write_text(p.read_text() + "z" * 8000)  # grew to ~23 KB: re-declining raises it
    rc, out, err = run(
        mem_cmd("no-split", "kit-long-argument", "-m", "still one", "--root", str(fx.store)),
        fx.env(),
    )
    assert rc == 0 and "until 30 KB" in out and "(was until 20 KB)" in out, out + err
    assert parse_frontmatter(p.read_text())[0]["splittable"] == "no until 30 KB: still one"

    small = fx.store / "territories/console/kit/kit-sync-design.md"
    before = small.read_text()
    rc, _, err = run(
        mem_cmd("no-split", "kit-sync-design", "-m", "x", "--root", str(fx.store)), fx.env()
    )
    assert rc == 2 and "nothing to decline" in err and small.read_text() == before
