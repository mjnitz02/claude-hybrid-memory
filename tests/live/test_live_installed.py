"""The INSTALLED `mem` against the REAL store on this machine. Read-only: nothing here writes.

    uv run pytest -m live

These run ~/.local/bin/mem, the binary settings.json calls, not the dev venv. That is what
catches an editable install left behind by a dependency change (docs/setup.md step 3):
the hook swallows the ImportError and prints nothing, which no fixture test can see.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import REPO, run

pytestmark = pytest.mark.live

STORE = Path.home() / ".claude" / "memory"
MEM = Path.home() / ".local" / "bin" / "mem"

if not STORE.is_dir():
    pytest.skip("no store on this machine", allow_module_level=True)
if not MEM.exists():
    pytest.skip("mem is not installed; see docs/setup.md step 3", allow_module_level=True)

READ_ONLY = [
    ["audit"], ["audit", "--json"], ["audit", "--scan", "legacy"], ["fix"], ["links"],
    ["fresh"], ["budget", "--json"], ["drift"], ["dup"], ["status", "--json"],
    ["log", "-n", "3"], ["render", "--check"], ["refine", "queue", "--limit", "3"],
]


@pytest.mark.parametrize("args", READ_ONLY, ids=" ".join)
def test_cli_runs_on_real_store(args: list[str]):
    rc, out, err = run([str(MEM), *args], dict(os.environ))
    assert rc in (0, 1), err
    assert "Traceback" not in err
    assert out or err.startswith("no memory files found")   # legacy, once every silo migrated


CWDS = [REPO, Path.home() / "workspaces" / "console_tools", Path.home() / "workspaces",
        Path("/tmp")]


@pytest.mark.parametrize("cwd", [c for c in CWDS if c.is_dir()], ids=str)
def test_hook_injects_the_layer(cwd: Path):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(cwd))
    rc, out, err = run([str(MEM), "hook", "session-start"], env, cwd)
    assert (rc, err) == (0, "")
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    # status only: past 10,000 chars the harness hands the model a 2 KB preview
    assert ctx.startswith("# MEMORY STATUS") and len(ctx) < 10_000
    always = (STORE / "ALWAYS.md").read_text(encoding="utf-8")
    assert "# GATES" in always and "# MEMORY ROUTER" in always


def test_index_counts_match_the_audit(tmp_path: Path):
    # Indexing writes <store>/.cache/, so it runs on a copy and the real store stays untouched.
    import shutil

    from claude_hybrid_memory.store import scan_store

    root = tmp_path / "memory"
    shutil.copytree(STORE, root, symlinks=True, ignore=shutil.ignore_patterns(".git", ".cache"))
    rc, out, err = run([str(MEM), "index", "--json", "--root", str(root)], dict(os.environ))
    assert (rc, err) == (0, "")
    by_area = json.loads(out)["by_area"]
    mems, _ = scan_store(root)
    assert by_area["territory"] + by_area["standing"] == len(mems)
    assert by_area.get("archive", 0) == len(list((root / "archive").rglob("*.md")))
    rc, out, _ = run([str(MEM), "find", "memory", "--root", str(root)], dict(os.environ))
    assert rc == 0 and out.strip() != "no matches"


def test_chains_agree_between_cache_and_audit(tmp_path: Path):
    # Same copy discipline as above. Every `supersedes:` on the real store must derive the
    # same edges whether read from the cache or straight from the markdown.
    import shutil
    import sqlite3

    from claude_hybrid_memory import cache
    from claude_hybrid_memory.audit.relations import store_graph

    root = tmp_path / "memory"
    shutil.copytree(STORE, root, symlinks=True, ignore=shutil.ignore_patterns(".git", ".cache"))
    rc, _, err = run([str(MEM), "index", "--root", str(root)], dict(os.environ))
    assert (rc, err) == (0, "")
    conn = sqlite3.connect(cache.db_path(root))
    assert cache.graph(conn).older == store_graph(root).older
    for (path,) in conn.execute("SELECT path FROM files WHERE meta LIKE '%supersedes%'"):
        rc, out, err = run([str(MEM), "history", path, "--root", str(root)], dict(os.environ))
        assert rc == 0 and "Supersedes (older):" in out, err
