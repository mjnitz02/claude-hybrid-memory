"""The PostToolUse hook, driven the way the harness drives it: JSON on stdin."""
from __future__ import annotations

import json
import subprocess

from conftest import Fixture, hook_cmd

from claude_hybrid_memory import events
from claude_hybrid_memory.harness import silo_name


def post(fx: Fixture, tool: str, path, session="s1") -> tuple[int, str]:
    cmd = hook_cmd()[:-1] + ["post-tool"]
    payload = {"session_id": session, "cwd": str(fx.repo), "hook_event_name": "PostToolUse",
               "tool_name": tool, "tool_input": {"file_path": str(path)},
               "tool_response": {}, "tool_use_id": "t1"}
    p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True,
                       env=fx.env(), timeout=30)
    return p.returncode, p.stdout


def evs(fx: Fixture) -> list[dict]:
    return list(events.read_all(fx.store))


def test_outside_the_store_is_ignored(fx: Fixture):
    assert post(fx, "Read", fx.repo / "src" / "main.py") == (0, "")
    assert post(fx, "Write", "/tmp/notes.md") == (0, "")
    assert not (fx.store / "events").exists()


def test_read_through_the_silo_symlink_logs_the_store_path(fx: Fixture):
    via_silo = fx.projects / silo_name(str(fx.repo)) / "memory" / "kit-sync-design.md"
    assert post(fx, "Read", via_silo) == (0, "")
    [e] = evs(fx)
    assert e["event"] == "read" and e["path"] == "territories/console/kit/kit-sync-design.md"
    assert e["session"] == "s1" and e["tool"] == "Read" and e["ts"].endswith("Z") and e["ms"] >= 0


def test_non_memory_files_in_the_store_are_ignored(fx: Fixture):
    (fx.store / "events").mkdir()
    assert post(fx, "Read", fx.store / "events" / "2026-10.jsonl") == (0, "")
    assert post(fx, "Read", fx.store / ".cache" / "x.md") == (0, "")
    assert evs(fx) == []


def test_new_lookalike_memory_gets_a_hint_and_an_edit_does_not(fx: Fixture):
    src = fx.store / "territories/home/lab/lab-backup-plan.md"
    new = fx.store / "territories/home/lab/lab-nightly-backups.md"
    new.write_text("---\nname: lab-nightly-backups\nkind: territory\n"
                   "description: lab backup plan — nightly backups, verified by hand\n---\n\n"
                   "Nightly at 03:00.\n")
    rc, out = post(fx, "Write", new)
    ctx = json.loads(out)["hookSpecificOutput"]
    assert rc == 0 and ctx["hookEventName"] == "PostToolUse"
    note = ctx["additionalContext"]
    assert "lab-backup-plan" in note and "supersedes:" in note
    # the same file edited later is not new to the cache: no repeated nagging
    new.write_text(new.read_text() + "\nMore.\n")
    assert post(fx, "Edit", new) == (0, "")
    assert post(fx, "Edit", src) == (0, "")
    assert [e["event"] for e in evs(fx)] == ["write", "write", "write"]


def test_new_unrelated_memory_gets_no_hint(fx: Fixture):
    new = fx.store / "territories/home/lab/lab-zeppelin-hangar.md"
    new.write_text("---\nname: lab-zeppelin-hangar\nkind: territory\n"
                   "description: airship mooring logistics for the hangar roof\n---\n\nBody.\n")
    assert post(fx, "Write", new) == (0, "")
    assert [e["path"] for e in evs(fx)] == ["territories/home/lab/lab-zeppelin-hangar.md"]


def test_garbage_on_stdin_never_breaks_the_session(fx: Fixture):
    cmd = hook_cmd()[:-1] + ["post-tool"]
    for stdin in ("", "not json " + str(fx.store), "{}"):
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=fx.env())
        assert (p.returncode, p.stdout) == (0, "")


# --- Bash: where most memory traffic actually goes ----------------------------------------

def bash(fx: Fixture, command: str, cwd=None, session="s1") -> tuple[int, str]:
    cmd = hook_cmd()[:-1] + ["post-tool"]
    payload = {"session_id": session, "cwd": str(cwd or fx.repo),
               "hook_event_name": "PostToolUse", "tool_name": "Bash",
               "transcript_path": str(fx.projects / "p" / "s1.jsonl"),
               "tool_input": {"command": command}, "tool_response": {}, "tool_use_id": "t1"}
    p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True,
                       env=fx.env(), timeout=30)
    return p.returncode, p.stdout


KIT = "territories/console/kit"


def test_bash_reads_writes_and_searches_are_logged(fx: Fixture):
    assert bash(fx, f"sed -n 1,20p ~/.claude/memory/{KIT}/kit-sync-design.md") == (0, "")
    assert bash(fx, f"cd ~/.claude/memory/{KIT} && rg -n sync kit-sync-v1.md 2>/dev/null") \
        == (0, "")
    assert bash(fx, f"cd $HOME/.claude/memory/{KIT} && python3 - <<'EOF'\n"
                    "Path('kit-sync-v1.md').write_text('x')\nEOF") == (0, "")
    assert bash(fx, "rg -n backup ~/.claude/memory/territories | head") == (0, "")
    got = [(e["event"], e["path"], e["tool"]) for e in evs(fx)]
    assert got == [("read", f"{KIT}/kit-sync-design.md", "Bash"),
                   ("read", f"{KIT}/kit-sync-v1.md", "Bash"),
                   ("write", f"{KIT}/kit-sync-v1.md", "Bash"),
                   ("search", "territories", "Bash")]
    assert all(e["ms"] >= 0 and e["session"] == "s1" for e in evs(fx))


def test_bash_relative_paths_resolve_against_a_cwd_in_the_store(fx: Fixture):
    assert bash(fx, "cat kit-sync-design.md", cwd=fx.store / KIT) == (0, "")
    assert [e["path"] for e in evs(fx)] == [f"{KIT}/kit-sync-design.md"]


def test_bash_outside_the_store_and_mem_itself_are_ignored(fx: Fixture):
    assert bash(fx, "git status && cat README.md") == (0, "")
    assert bash(fx, "ls ~/.claude/memory/events/ && cat ~/.claude/memory/.cache/x.md") == (0, "")
    # `mem` logs its own reads, so the hook does not count them twice
    assert bash(fx, f"mem show ~/.claude/memory/{KIT}/kit-sync-design.md") == (0, "")
    assert bash(fx, f"cat ~/.claude/memory/{KIT}/*.md") == (0, "")
    assert evs(fx) == []


def test_mem_show_and_find_log_their_own_reads(fx: Fixture):
    from conftest import mem_cmd, run
    env = {**fx.env(), "CLAUDE_CODE_SESSION_ID": "s9"}
    assert run(mem_cmd("show", "kit-sync-design"), env)[0] == 0
    assert run(mem_cmd("find", "sync"), env)[0] == 0
    show, find = evs(fx)
    assert (show["event"], show["path"], show["tool"], show["session"]) == (
        "read", f"{KIT}/kit-sync-design.md", "mem show", "s9")
    assert (find["event"], find["tool"], find["query"]) == ("search", "mem find", ["sync"])
    assert f"{KIT}/kit-sync-design.md" in find["hits"]
