"""The store's own history: `mem commit | log | diff` and the SessionEnd hook (direction §16.1)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import Fixture, hook_cmd, mem_cmd, run

from claude_hybrid_memory import events, storegit


def git(root, *args) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def init(root) -> None:
    """A store as setup.md step 1b leaves it: its own repo and a baseline commit."""
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / ".gitignore").write_text(".cache/\nALWAYS.md\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Baseline")


def end(fx: Fixture, payload: str) -> tuple[int, str, str]:
    p = subprocess.run(
        hook_cmd()[:-1] + ["session-end"],
        input=payload,
        capture_output=True,
        text=True,
        env=fx.env(),
        timeout=30,
    )
    return p.returncode, p.stdout, p.stderr


def subjects(root) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


def test_session_end_commits_memory_and_events(fx: Fixture):
    init(fx.store)
    (fx.store / "territories/home/lab/lab-new-note.md").write_text(
        "---\nname: lab-new-note\nkind: territory\ndescription: New.\n---\n\nBody.\n"
    )
    (fx.store / "standing/working-register.md").write_text("changed\n")
    (fx.store / "territories/console/kit/kit-sync-v1.md").unlink()
    for _ in range(3):
        events.append(fx.store, {"event": "read", "path": "standing/working-register.md"})
    (fx.store / ".cache").mkdir()
    (fx.store / ".cache/index.sqlite").write_text("derived")

    payload = json.dumps(
        {"session_id": "sess-1", "hook_event_name": "SessionEnd", "reason": "clear"}
    )
    assert end(fx, payload) == (0, "", "")
    subject, base = subjects(fx.store)
    assert base == "Baseline"
    # ROUTER.md too: session end keeps its counts true (console/kit lost one, home/lab gained one)
    assert subject == (
        "mem: 1 added, 2 modified, 1 deleted in ROUTER.md, standing, console/kit +1 more; 3 events"
    )
    body = git(fx.store, "log", "-1", "--format=%b")
    assert "Trigger: session end (clear) · session sess-1" in body
    assert "A  territories/home/lab/lab-new-note.md" in body
    assert "D  territories/console/kit/kit-sync-v1.md" in body
    assert git(fx.store, "status", "--porcelain") == ""
    assert ".cache/index.sqlite" not in git(fx.store, "ls-files")


def test_nothing_to_commit_is_clean_not_an_empty_commit(fx: Fixture):
    init(fx.store)
    assert storegit.commit(fx.store, "test").status == "clean"
    assert subjects(fx.store) == ["Baseline"]


def test_events_only_commit(fx: Fixture):
    init(fx.store)
    events.append(fx.store, {"event": "read", "path": "x.md"})
    r = storegit.commit(fx.store, "test")
    assert (r.status, r.detail) == ("committed", "mem: 1 usage events")


def test_never_commits_into_a_parent_repository(fx: Fixture):
    # The store is not its own repo but sits inside one: `git -C` alone would commit there.
    init(fx.home)
    before = subjects(fx.home)
    (fx.store / "standing/working-register.md").write_text("changed\n")
    r = storegit.commit(fx.store, "test")
    assert r.status == "skipped" and "not a git repository" in r.detail
    assert subjects(fx.home) == before
    assert end(fx, "{}") == (0, "", "")
    assert subjects(fx.home) == before


def test_a_hook_environment_never_redirects_the_commit(fx: Fixture, monkeypatch):
    # Under another repo's git hook, GIT_DIR and GIT_INDEX_FILE point at that repo and
    # outrank `-C`. The store's commit must still land in the store and only there.
    init(fx.store)
    outer = fx.home / "outer"
    outer.mkdir()
    init(outer)
    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(outer / ".git" / "index"))
    (fx.store / "standing/working-register.md").write_text("changed\n")
    assert storegit.commit(fx.store, "test").status == "committed"
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert subjects(outer) == ["Baseline"]
    assert len(subjects(fx.store)) == 2


def test_a_held_index_lock_skips_and_the_hook_stays_silent(fx: Fixture):
    init(fx.store)
    (fx.store / "standing/working-register.md").write_text("changed\n")
    (fx.store / ".git/index.lock").write_text("")
    assert storegit.commit(fx.store, "test").status == "skipped"
    assert end(fx, "not json") == (0, "", "")
    assert subjects(fx.store) == ["Baseline"]


def test_mem_commit_takes_a_subject_and_keeps_the_generated_body(fx: Fixture):
    init(fx.store)
    (fx.store / "standing/working-register.md").write_text("changed\n")
    env = {**fx.env(), "CLAUDE_CODE_SESSION_ID": "sess-2"}
    rc, out, _ = run(mem_cmd("commit", "-m", "Reword the register directive"), env)
    assert rc == 0 and out.split("  ", 1)[1].strip() == "Reword the register directive"
    body = git(fx.store, "log", "-1", "--format=%b")
    assert "Trigger: mem commit · session sess-2" in body
    assert "M  standing/working-register.md" in body
    rc, out, _ = run(mem_cmd("commit"), env)
    assert (rc, out.strip()) == (0, "clean: nothing to commit")


def test_mem_log_and_diff_are_read_only(fx: Fixture):
    init(fx.store)
    (fx.store / "standing/working-register.md").write_text("changed\n")
    (fx.store / "standing/brand-new.md").write_text("new\n")
    rc, out, _ = run(mem_cmd("diff", "--stat"), fx.env())
    assert rc == 0 and "standing/working-register.md" in out
    assert "1 untracked (new) file:\n  standing/brand-new.md" in out
    rc, out, _ = run(mem_cmd("log", str(fx.store / "standing/working-register.md")), fx.env())
    assert rc == 0 and out.rstrip().endswith("Baseline")
    assert len(git(fx.store, "status", "--porcelain").splitlines()) == 2


def test_mem_commit_without_a_repository_is_a_tool_error(fx: Fixture):
    rc, _, err = run(mem_cmd("commit"), fx.env())
    assert rc == 2 and "not a git repository" in err


def test_area_names_where_a_path_lives():
    assert storegit.area("territories/console/tools/x.md") == "console/tools"
    assert storegit.area("standing/x.md") == "standing"
    assert storegit.area("archive/kit-old/x.md") == "archive/kit-old"
    assert storegit.area("ROUTER.md") == "ROUTER.md"


# --- restore, show --at, audit --at: the rest of git, through mem ------------------------

LAB = "territories/home/lab/lab-backup-plan.md"


def test_restore_puts_files_back_and_commits_what_it_overwrites_first(fx: Fixture):
    init(fx.store)
    original = (fx.store / LAB).read_text()
    (fx.store / LAB).write_text("edited\n")
    (fx.store / "territories/home/lab/lab-new-note.md").write_text("added since\n")
    rc, out, _ = run(mem_cmd("restore", "home/lab"), fx.env())
    assert rc == 0 and "committed first" in out and f"restored   {LAB}" in out
    assert (fx.store / LAB).read_text() == original
    assert (fx.store / "territories/home/lab/lab-new-note.md").read_text() == "added since\n"
    # the overwritten edit is the safety commit's, one step back
    assert git(fx.store, "show", f"HEAD:{LAB}") == "edited\n"
    assert "before mem restore from HEAD" in git(fx.store, "log", "-1", "--format=%b")
    rc, out, _ = run(mem_cmd("restore", LAB, "--from", "HEAD~1"), fx.env())
    assert rc == 0 and (fx.store / LAB).read_text() == original
    assert f"unchanged  {LAB}" in out


def test_revert_undoes_a_store_commit_as_a_new_one(fx: Fixture):
    # the undo a restructure step prints; a session never runs `git revert` on the store
    init(fx.store)
    original = (fx.store / LAB).read_text()
    (fx.store / LAB).write_text("edited\n")
    rc, out, _ = run(mem_cmd("commit", "-m", "an edit"), fx.env())
    sha = out.split()[0]
    rc, out, _ = run(mem_cmd("revert", sha), fx.env())
    assert rc == 0 and "reverted 1 commit(s)" in out
    assert (fx.store / LAB).read_text() == original
    assert subjects(fx.store)[:2][1] == "an edit"  # history kept, never rewritten
    rc, _, err = run(mem_cmd("revert", "nope"), fx.env())
    assert rc == 1 and err


def test_restore_writes_nothing_when_any_path_is_wrong(fx: Fixture):
    init(fx.store)
    (fx.store / LAB).write_text("edited\n")
    rc, _, err = run(mem_cmd("restore", LAB, "standing/no-such.md"), fx.env())
    assert rc == 1 and "not in HEAD: standing/no-such.md" in err
    assert (fx.store / LAB).read_text() == "edited\n"
    assert subjects(fx.store) == ["Baseline"]
    rc, _, err = run(mem_cmd("restore", LAB, "--from", "nope"), fx.env())
    assert rc == 1 and "names no commit" in err
    assert storegit.restore(fx.store, [LAB], "nope").detail == "'nope' names no commit in the store"
    assert "outside the store" in storegit.restore(fx.store, ["../x.md"]).detail


def test_show_at_reads_a_past_version_even_of_a_deleted_file(fx: Fixture):
    init(fx.store)
    original = (fx.store / LAB).read_text()
    (fx.store / LAB).write_text("---\nname: lab-backup-plan\nkind: territory\n---\n\nNew.\n")
    rc, out, _ = run(mem_cmd("show", "lab-backup-plan", "--at", "HEAD", "--full"), fx.env())
    assert rc == 0 and out == original
    (fx.store / "territories/console/kit/kit-sync-v1.md").unlink()
    rc, out, _ = run(
        mem_cmd("show", "console/kit/kit-sync-v1.md", "--at", "HEAD", "--meta"), fx.env()
    )
    assert rc == 0 and "description: The first sync cut." in out
    rc, _, err = run(mem_cmd("show", "lab-backup-plan", "--at", "nope"), fx.env())
    assert rc == 2 and "names no commit" in err
    assert git(fx.store, "status", "--porcelain").count("\n") == 2


def test_audit_at_checks_a_past_store_and_names_live_paths(fx: Fixture):
    init(fx.store)
    p = fx.store / "territories/console/kit/kit-sync-design.md"
    p.write_text(p.read_text() + "\napi_key: 9f8e7d6c5b4a39281706f5e4\n")
    now = json.loads(run(mem_cmd("audit", "--json", "--scan", "store"), fx.env())[1])
    rc, out, _ = run(mem_cmd("audit", "--json", "--scan", "store", "--at", "HEAD"), fx.env())
    then = json.loads(out)

    def key(fs):
        return {(f["code"], f["path"]) for f in fs}

    assert key(now) - key(then) == {("secret-maybe", str(p))}
    assert not [f["path"] for f in then if "mem-at-" in f["path"] + f["message"]]
    rc, out, _ = run(mem_cmd("audit", "--scan", "store", "--at", "HEAD"), fx.env())
    assert out.startswith(f"{fx.store} at HEAD (")
    rc, _, err = run(mem_cmd("fix", "--at", "HEAD"), fx.env())
    assert rc == 2 and "read-only" in err


def test_only_storegit_runs_git():
    """direction §16.1: storegit.py is the one place `mem` runs git."""
    src = Path(__file__).resolve().parents[1] / "src" / "claude_hybrid_memory"
    offenders = [
        str(f.relative_to(src))
        for f in src.rglob("*.py")
        if '"git"' in f.read_text() and f.name != "storegit.py"
    ]
    assert offenders == []


def test_events_stats_reports_stale_writes_per_session(fx: Fixture):
    """A write to a memory past its window with no `mem verified` from that session is a miss,
    judged as of the session's first touch; a later check by another session does not hide it."""
    import datetime as dt

    def mem(slug: str, verified: dt.date) -> str:
        path = f"territories/home/lab/{slug}.md"
        (fx.store / path).write_text(
            f"---\nname: {slug}\nkind: territory\ndescription: X.\nvolatility: live\n"
            f"last_verified: {verified}\n---\n\nBody.\n"
        )
        return path

    day = dt.date.today() + dt.timedelta(days=2)
    stale = mem("lab-stale", day - dt.timedelta(days=20))
    fresh = mem("lab-fresh", day - dt.timedelta(days=3))
    checked = mem("lab-checked", day - dt.timedelta(days=20))
    init(fx.store)
    rows = [
        ("a", "read", stale, "10"),
        ("a", "write", stale, "11"),
        ("a", "write", fresh, "12"),
        ("a", "write", "territories/home/lab/MEMORY.md", "13"),
        ("b", "write", checked, "14"),
        ("b", "verified", checked, "15"),
        ("c", "verified", stale, "16"),
    ]
    (fx.store / "events").mkdir(exist_ok=True)
    with (fx.store / f"events/{day:%Y-%m}.jsonl").open("a") as fh:
        for session, kind, path, hh in rows:
            ts = f"{day}T{hh}:00:00.000Z"
            rec = {"ts": ts, "event": kind, "path": path, "session": session, "cwd": "/x/repo"}
            fh.write(json.dumps(rec) + "\n")

    code, out, _ = run(mem_cmd("events", "stats", "--json"), env=fx.env())
    assert code == 0
    sw = json.loads(out)["stale_writes"]
    assert [(w["session"], w["path"]) for w in sw] == [("a", stale)]
    assert sw[0]["age"] == 20 and sw[0]["verified_later"] == [str(day)]
    code, out, _ = run(mem_cmd("events", "stats"), env=fx.env())
    assert "no `mem verified` from that session: 1" in out
    assert "session a in repo; checked later" in out
