"""The plugin's own files agree with the code: manifest names, hooks, the `bin/mem` shim.

`claude plugin validate` is not run here, so CI needs no Claude CLI; it is run by hand when
these files change (setup.md, "The plugin").
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import REPO

from claude_hybrid_memory import install

MANIFEST = REPO / ".claude-plugin"


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_plugin_and_marketplace_name_the_same_plugin():
    plugin = load(MANIFEST / "plugin.json")
    market = load(MANIFEST / "marketplace.json")
    assert plugin["name"] == install.PLUGIN == market["name"]
    [entry] = market["plugins"]
    assert entry["name"] == install.PLUGIN and entry["source"] == "./"
    assert entry["description"] == plugin["description"]
    # no version: every commit on main is a release (direction §16, 2026-11-03)
    assert "version" not in plugin and "version" not in entry


def test_hooks_json_runs_each_mem_hook_through_the_shim():
    hooks = load(REPO / "hooks" / "hooks.json")["hooks"]
    assert set(hooks) == set(install.HOOKS)
    for event, (matcher, name) in install.HOOKS.items():
        [group] = hooks[event]
        assert group.get("matcher") == matcher, event
        [hook] = group["hooks"]
        assert hook["command"] == f'"${{CLAUDE_PLUGIN_ROOT}}/bin/mem" hook {name}'
        assert install.is_ours(hook, name)  # so `mem install` would know it for its own
        # session start may build the venv on first run; the others fire constantly
        assert hook["timeout"] == (60 if event == "SessionStart" else 10)


def test_no_directory_a_plugin_would_misread():
    # agents/ loads as subagents; mem's claude -p prompts live in prompts/
    assert not (REPO / "agents").exists() and (REPO / "prompts").is_dir()
    assert os.access(REPO / "bin" / "mem", os.X_OK)


def shim_without_uv(tmp_path: Path) -> Path:
    """A copy of the plugin's shim on a box with no uv anywhere it looks."""
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    text = (REPO / "bin" / "mem").read_text()
    text = text.replace('"$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv',
                        "/nonexistent/uv")
    assert "/nonexistent/uv" in text
    f = root / "bin" / "mem"
    f.write_text(text)
    f.chmod(0o755)
    return f


def test_shim_without_uv_fails_open_and_says_why(tmp_path: Path):
    f = shim_without_uv(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path / "c")}

    def go(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(f), *args], capture_output=True, text=True, env=env, input="")

    p = go("hook", "session-start")
    ctx = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
    assert p.returncode == 0 and "needs uv" in ctx
    p = go("hook", "post-tool")
    assert p.returncode == 0 and p.stdout == ""
    p = go("audit")
    assert p.returncode == 127 and "needs uv" in p.stderr


def test_shim_fast_path_runs_the_stamped_venv(tmp_path: Path):
    # a venv stamped for this root is exec'd directly, with no uv involved
    f = shim_without_uv(tmp_path)
    root = f.parent.parent.resolve()
    (root / "uv.lock").write_text("")
    venv = tmp_path / "c" / "claude-hybrid-memory" / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "mem").write_text('#!/bin/sh\necho "venv mem $*"\n')
    (venv / "bin" / "mem").chmod(0o755)
    (venv / ".plugin-root").write_text(f"{root}\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path / "c")}
    p = subprocess.run([str(f), "log", "-n", "1"], capture_output=True, text=True, env=env)
    assert p.stdout == "venv mem log -n 1\n", p.stderr
    # a newer uv.lock means a dependency changed: the fast path is refused (and, with no
    # uv here, the call fails rather than running a stale venv)
    os.utime(root / "uv.lock", (2e9, 2e9))
    p = subprocess.run([str(f), "log"], capture_output=True, text=True, env=env)
    assert p.returncode == 127 and "venv mem" not in p.stdout
