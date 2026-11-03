"""`mem install`: the scripted setup.md steps 1 to 3c, run against a throwaway home."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO, mem_cmd, run

from claude_hybrid_memory import install
from claude_hybrid_memory.hooks import session_start

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


def plugin(home: Path) -> Path:
    """Mark the plugin installed from a marketplace, as Claude Code records it."""
    f = home / ".claude" / "plugins" / "installed_plugins.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"version": 2, "plugins": {
        "hybrid-memory@hybrid-memory": [{"scope": "user"}]}}))
    return f


def legacy(home: Path, other: dict) -> Path:
    """A machine wired up before the plugin: mem hooks in settings.json, one link per skill."""
    claude = home / ".claude"
    (claude / "skills").mkdir(parents=True, exist_ok=True)
    for s in ("memory-setup", "memory-retro"):
        (claude / "skills" / s).symlink_to(REPO / "skills" / s)
    path = claude / "settings.json"
    path.write_text(json.dumps({
        "model": "opus",
        "hooks": {
            "PostToolUse": [
                # someone else's hook sharing a group with ours: theirs stays, with its matcher
                {"matcher": "Edit", "hooks": [other, {"type": "command",
                                                       "command": "/old/path/mem hook post-tool"}]},
            ],
            "SessionStart": [
                {"hooks": [{"type": "command",
                            "command": "/usr/bin/python3 tools/session_start.py"}]},
                {"hooks": [{"type": "command", "command": "/home/x/.local/bin/mem",
                            "args": ["hook", "session-start"]}]},
            ],
            "SessionEnd": [{"hooks": [{"type": "command", "command": "mem",
                                       "args": ["hook", "session-end"]}]}],
            "Stop": [{"hooks": [other]}],
        },
    }))
    return path


def test_fresh_machine_gets_store_history_and_no_settings(home: Path):
    plugin(home)
    f = do(home)
    store = home / ".claude" / "memory"
    assert all((store / d).is_dir() for d in install.DIRS)
    assert all((store / t).is_file() for t in install.TEMPLATES)
    assert "install-edit-machine" in codes(f)
    log = subprocess.run(["git", "-C", str(store), "log", "--format=%s"], capture_output=True,
                         text=True).stdout
    assert log.startswith("Baseline: store as of")
    assert ".bm25-index.json" in (store / ".gitignore").read_text()
    # the plugin carries hooks and skills: nothing is written for them
    assert not (home / ".claude" / "settings.json").exists()
    assert not [p for p in (home / ".claude" / "skills").glob("*") if p.is_symlink()]


def test_second_run_changes_nothing(home: Path):
    plugin(home)
    do(home)
    f = do(home)
    assert codes(f) <= {"install-ok", "install-check-skipped"}, f


def test_dry_run_writes_nothing(home: Path):
    f = do(home, dry=True)
    assert not home.exists()
    assert any(x.message.startswith("would") for x in f)


def test_no_plugin_warns_and_keeps_the_old_wiring(home: Path):
    # removing the old hooks with no plugin to replace them would leave no hooks at all
    other = {"type": "command", "command": "/usr/local/bin/notify"}
    path = legacy(home, other)
    before = path.read_text()
    f = do(home)
    assert "install-no-plugin" in codes(f)
    assert path.read_text() == before
    assert (home / ".claude" / "skills" / "memory-retro").is_symlink()


def test_with_the_plugin_the_old_wiring_is_removed(home: Path):
    other = {"type": "command", "command": "/usr/local/bin/notify"}
    path = legacy(home, other)
    plugin(home)
    dry = do(home, dry=True)
    assert {"install-legacy-hook", "install-legacy-skill"} <= codes(dry)
    assert (home / ".claude" / "skills" / "memory-retro").is_symlink()
    f = do(home)
    s = json.loads(path.read_text())
    assert s == {"model": "opus", "hooks": {"PostToolUse": [{"matcher": "Edit",
                                                             "hooks": [other]}],
                                            "Stop": [{"hooks": [other]}]}}
    assert sum(x.code == "install-legacy-hook" and "removed" in x.message for x in f) == 3
    assert len(list(path.parent.glob("settings.json.bak-*"))) == 1
    assert not (home / ".claude" / "skills" / "memory-retro").exists()
    assert not (home / ".claude" / "skills" / "memory-setup").exists()


def test_unreadable_settings_are_left_alone(home: Path):
    plugin(home)
    path = home / ".claude" / "settings.json"
    path.write_text("{not json")
    f = do(home)
    assert "install-settings" in codes(f) and path.read_text() == "{not json"


def test_store_inside_another_checkout_is_not_initialized(home: Path):
    home.mkdir(parents=True)
    subprocess.run(["git", "-C", str(home), "init", "-q"], check=True)
    f = do(home)
    assert "install-git" in codes(f) and not (home / ".claude" / "memory" / ".git").exists()


def test_a_real_skill_directory_is_not_removed(home: Path):
    plugin(home)
    mine = home / ".claude" / "skills" / "memory-retro"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("mine\n")
    do(home)
    assert (mine / "SKILL.md").read_text() == "mine\n"


def test_dev_links_the_checkout_as_the_plugin(home: Path):
    claude = home / ".claude"
    dry = install.run(claude / "memory", REPO, claude, Path(MEM), True, dev=True)
    assert "install-dev-link" in codes(dry) and "install-no-plugin" not in codes(dry)
    assert not home.exists()
    f = install.run(claude / "memory", REPO, claude, Path(MEM), False, dev=True)
    link = claude / "skills" / "hybrid-memory"
    assert link.is_symlink() and link.resolve() == REPO.resolve()
    assert install.plugin_source(claude) == "skills-dir"
    assert "install-no-plugin" not in codes(f)
    again = install.run(claude / "memory", REPO, claude, Path(MEM), False, dev=True)
    assert "install-dev-link" not in codes(again)


def test_dev_never_replaces_a_real_directory(home: Path):
    real = home / ".claude" / "skills" / "hybrid-memory"
    real.mkdir(parents=True)
    f = install.run(home / ".claude" / "memory", REPO, home / ".claude", Path(MEM), False,
                    dev=True)
    assert any(x.code == "install-dev-link" and x.level == "error" for x in f)
    assert real.is_dir() and not real.is_symlink()


def test_existing_gitignore_gets_missing_patterns(home: Path):
    do(home)
    ignore = home / ".claude" / "memory" / ".gitignore"
    ignore.write_text(".cache/\n")
    do(home)
    assert ignore.read_text().splitlines() == [".cache/", ".DS_Store", ".bm25-index.json",
                                               "ALWAYS.md"]


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


def test_rules_file_imports_the_layer_and_is_owned(home: Path):
    store, claude = home / ".claude" / "memory", home / ".claude"
    assert "install-rules" in codes(do(home))
    rules = session_start.rules_path(claude / "CLAUDE.md")
    assert rules == claude / "rules" / "claude-hybrid-memory.md"
    assert session_start.import_line(store) in rules.read_text().splitlines()
    assert session_start.importers(store, claude / "CLAUDE.md") == [rules]
    assert not (claude / "CLAUDE.md").exists()  # never created, never written
    rules.write_text("hand edit\n")  # mem owns it: drift is rewritten, dry run only says so
    assert "would rewrite" in " ".join(x.message for x in do(home, dry=True))
    assert rules.read_text() == "hand edit\n"
    do(home)
    assert rules.read_text() == session_start.rules_text(store)


def test_a_claude_md_import_too_is_reported_never_written(home: Path):
    md = home / ".claude" / "CLAUDE.md"
    md.parent.mkdir(parents=True)
    line = session_start.import_line(home / ".claude" / "memory")  # this home is not ~
    md.write_text(f"# Git\n\nOnly touch git when asked.\n\n# Memory\n\n{line}\n")
    before = md.read_text()
    f = do(home)
    assert "install-imported-twice" in codes(f)
    assert md.read_text() == before
    md.write_text("# Git\n\nOnly touch git when asked.\n")
    assert "install-imported-twice" not in codes(do(home))
