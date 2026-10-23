"""The hook path runs at the start of every session (and, from Phase 2, after every tool
call), so what it imports is a budget, not a style preference."""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time

from conftest import Fixture, hook_cmd, run

PROBE = """
import sys
from claude_hybrid_memory import cli
cli._hook(["session-start"])
print(__import__("json").dumps(sorted(m for m in sys.modules
      if m.startswith("claude_hybrid_memory") or m in ("argparse", "subprocess", "dataclasses",
                                                       "yaml", "sqlite3"))))
"""


def test_hook_path_imports_nothing_it_does_not_need(fx: Fixture):
    p = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True,
                       env=fx.env())
    loaded = json.loads(p.stdout.strip().splitlines()[-1])
    assert loaded == ["claude_hybrid_memory", "claude_hybrid_memory.cli",
                      "claude_hybrid_memory.harness", "claude_hybrid_memory.hooks",
                      "claude_hybrid_memory.hooks.session_start"]


def test_hook_wall_time(fx: Fixture):
    # Generous on purpose: the plan's budget is 50 ms p95 under uv; this guards against a
    # regression of a different order (an import that costs hundreds of ms), not jitter.
    times = []
    for _ in range(5):
        t = time.perf_counter()
        rc, out, _ = run(hook_cmd(), fx.env())
        times.append(time.perf_counter() - t)
        assert rc == 0 and out
    assert statistics.median(times) < 0.25


POST_PROBE = """
import io, json, sys
from claude_hybrid_memory import cli
sys.stdin = io.StringIO(json.dumps({"tool_name": "Read", "tool_input": {"file_path": sys.argv[1]}}))
cli._hook(["post-tool"])
print(json.dumps(sorted(m for m in sys.modules
      if m.startswith("claude_hybrid_memory") or m in ("argparse", "subprocess", "dataclasses",
                                                       "yaml", "sqlite3"))))
"""


def _post_loaded(fx: Fixture, path) -> list[str]:
    p = subprocess.run([sys.executable, "-c", POST_PROBE, str(path)], capture_output=True,
                       text=True, env=fx.env())
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_post_tool_outside_the_store_imports_only_itself(fx: Fixture):
    # Every Read/Write/Edit in every session pays for this path.
    assert _post_loaded(fx, fx.repo / "src" / "main.py") == [
        "claude_hybrid_memory", "claude_hybrid_memory.cli", "claude_hybrid_memory.hooks",
        "claude_hybrid_memory.hooks.post_tool"]


def test_post_tool_store_read_stays_off_sqlite_and_yaml(fx: Fixture):
    assert _post_loaded(fx, fx.store / "territories/console/kit/kit-sync-design.md") == [
        "claude_hybrid_memory", "claude_hybrid_memory.cli", "claude_hybrid_memory.events",
        "claude_hybrid_memory.hooks", "claude_hybrid_memory.hooks.post_tool"]



def test_post_tool_rejects_an_ordinary_payload_before_parsing_it():
    # Every Bash call in every session pays for this path. The transcript path sits under
    # projects/ in every payload, so projects/ alone must not count as a match.
    from claude_hybrid_memory.hooks import post_tool as pt
    t = str(pt.PROJECTS / "-Users-x-repo" / "s1.jsonl")
    assert not pt._maybe_memory(json.dumps({"tool_name": "Bash", "transcript_path": t,
                                            "tool_input": {"command": "git status"}}))
    assert pt._maybe_memory(json.dumps({"tool_input": {"command": "cat ~/.claude/memory/x.md"}}))
    assert pt._maybe_memory(json.dumps({"tool_input": {
        "file_path": str(pt.PROJECTS / "-Users-x-repo" / "memory" / "x.md")}}))
