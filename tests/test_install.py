"""`mem install`: the scripted setup.md steps 1 to 3c, run against a throwaway home."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO, mem_cmd, run

from claude_hybrid_memory import install

MEM = "/opt/fixture/bin/mem"


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "Fixture")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "fixture@example.invalid")
    return tmp_path / "home"


def do(home: Path, dry: bool = False, mem: str = MEM):
    return install.run(home / ".claude" / "memory", REPO, home / ".claude", Path(mem), dry)


def shim(tmp_path: Path, body: str | None = None) -> str:
    """A `mem` binary: this checkout's, or a broken one that runs `body` instead."""
    f = tmp_path / "bin" / "mem"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("#!/bin/sh\n"
                 + (body or f'exec "{sys.executable}" -m claude_hybrid_memory "$@"\n'))
    f.chmod(0o755)
    return str(f)


def codes(findings) -> set[str]:
    return {f.code for f in findings}


def test_fresh_machine_gets_store_history_skills_and_hooks(home: Path):
    f = do(home)
    store = home / ".claude" / "memory"
    assert all((store / d).is_dir() for d in install.DIRS)
    assert all((store / t).is_file() for t in install.TEMPLATES)
    assert "install-edit-machine" in codes(f)
    log = subprocess.run(["git", "-C", str(store), "log", "--format=%s"], capture_output=True,
                         text=True).stdout
    assert log.startswith("Baseline: store as of")
    assert ".bm25-index.json" in (store / ".gitignore").read_text()
    for s in ("memory-setup", "memory-migrate", "memory-retro"):
        assert (home / ".claude" / "skills" / s).resolve() == (REPO / "skills" / s).resolve()
    hooks = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]
    assert hooks["SessionStart"] == [install.hook_group("SessionStart", MEM)]
    assert hooks["PostToolUse"][0]["matcher"] == "Read|Write|Edit|Bash"
    assert "matcher" not in hooks["SessionEnd"][0]


def test_second_run_changes_nothing(home: Path):
    do(home)
    settings = (home / ".claude" / "settings.json").read_text()
    f = do(home)
    assert codes(f) <= {"install-ok", "install-mem-missing", "install-git-exception",
                        "install-check-skipped"}, f
    assert (home / ".claude" / "settings.json").read_text() == settings
    assert not list((home / ".claude").glob("settings.json.bak-*"))


def test_dry_run_writes_nothing(home: Path):
    f = do(home, dry=True)
    assert not home.exists()
    assert any(x.message.startswith("would") for x in f)


def test_existing_settings_are_merged_not_replaced(home: Path):
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    other = {"type": "command", "command": "/usr/local/bin/notify"}
    path.write_text(json.dumps({
        "model": "opus",
        "hooks": {
            "PostToolUse": [
                # someone else's hook sharing a group with ours: theirs keeps its matcher
                {"matcher": "Edit", "hooks": [other, {"type": "command",
                                                       "command": "/old/path/mem hook post-tool"}]},
            ],
            "SessionStart": [
                {"hooks": [{"type": "command",
                            "command": "/usr/bin/python3 tools/session_start.py"}]},
                {"hooks": [{"type": "command", "command": "mem",
                            "args": ["hook", "session-start"]}]},
            ],
            "Stop": [{"hooks": [other]}],
        },
    }))
    f = do(home)
    s = json.loads(path.read_text())
    assert s["model"] == "opus" and s["hooks"]["Stop"] == [{"hooks": [other]}]
    assert s["hooks"]["PostToolUse"] == [install.hook_group("PostToolUse", MEM),
                                         {"matcher": "Edit", "hooks": [other]}]
    assert s["hooks"]["SessionStart"] == [install.hook_group("SessionStart", MEM)]
    assert any("duplicate" in x.message for x in f)
    assert len(list(path.parent.glob("settings.json.bak-*"))) == 1


def test_unreadable_settings_are_left_alone(home: Path):
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    f = do(home)
    assert "install-settings" in codes(f) and path.read_text() == "{not json"


def test_store_inside_another_checkout_is_not_initialized(home: Path):
    home.mkdir(parents=True)
    subprocess.run(["git", "-C", str(home), "init", "-q"], check=True)
    f = do(home)
    assert "install-git" in codes(f) and not (home / ".claude" / "memory" / ".git").exists()


def test_a_real_skill_directory_is_not_replaced(home: Path):
    mine = home / ".claude" / "skills" / "memory-retro"
    mine.mkdir(parents=True)
    f = do(home)
    assert mine.is_dir() and not mine.is_symlink()
    assert any(x.code == "install-skill" and x.level == "warn" for x in f)


def test_existing_gitignore_gets_missing_patterns(home: Path):
    do(home)
    ignore = home / ".claude" / "memory" / ".gitignore"
    ignore.write_text(".cache/\n")
    do(home)
    assert ignore.read_text().splitlines() == [".cache/", ".DS_Store", ".bm25-index.json"]


def test_cli(home: Path, tmp_path: Path):
    rc, out, err = run(mem_cmd("install", "--dry-run", "--root", str(home / "store"),
                               "--claude-dir", str(home / ".claude"), "--mem", MEM),
                       {"PATH": "/usr/bin:/bin"})
    assert rc == 0, err
    assert "would" in out and not home.exists()
    rc, _, err = run(mem_cmd("install", "--repo", str(tmp_path)), {"PATH": "/usr/bin:/bin"})
    assert rc == 2 and "templates" in err


def test_hooks_are_run_against_a_copy_of_the_store(home: Path, tmp_path: Path):
    f = do(home, mem=shim(tmp_path))
    ok = {x.code for x in f if x.level == "info"}
    assert {"install-check-session-start", "install-check-post-tool",
            "install-check-session-end"} <= ok, f
    store = home / ".claude" / "memory"
    assert not (store / "events").exists()      # the read was logged in the copy only
    assert subprocess.run(["git", "-C", str(store), "rev-list", "--count", "HEAD"],
                          capture_output=True, text=True).stdout.strip() == "1"


def test_a_hook_that_fails_open_is_still_caught(home: Path, tmp_path: Path):
    # what a missing dependency looks like: every hook exits 0 and does nothing
    f = do(home, mem=shim(tmp_path, "exit 0\n"))
    bad = {x.code for x in f if x.level == "error"}
    assert bad == {"install-check-session-start", "install-check-post-tool",
                   "install-check-session-end"}


def test_claude_md_exception_is_checked_never_written(home: Path):
    md = home / ".claude" / "CLAUDE.md"
    md.parent.mkdir(parents=True)
    md.write_text("# Git\n\nOnly touch git when asked.\n")
    assert "install-git-exception" in codes(do(home))
    assert md.read_text() == "# Git\n\nOnly touch git when asked.\n"
    md.write_text("# Git\n\nOnly touch git when asked.\n\n"
                  + (REPO / "templates" / "CLAUDE-git-exception.md").read_text())
    assert "install-git-exception" not in codes(do(home))
