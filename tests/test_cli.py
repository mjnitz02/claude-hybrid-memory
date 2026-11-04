"""The CLI surface the 2026-11-04 usability eval tripped on: one parser's worth of polish
across every command, flags in either position, `mem show <territory>`, and the
no-territory hook naming the command to run. Synthetic fixtures throughout."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import Fixture, mem_cmd, run

from claude_hybrid_memory.cli import _hoist
from claude_hybrid_memory.hooks.session_start import guess_territory


def test_global_flags_before_the_subcommand_move_after_it():
    assert _hoist(["--root", "X", "find", "reader"]) == ["find", "reader", "--root", "X"]
    assert _hoist(["--root=X", "--json", "verified", "s", "-m", "n"]) == \
        ["verified", "s", "-m", "n", "--root=X", "--json"]
    assert _hoist(["-t", "a/b", "new", "slug"]) == ["new", "slug", "-t", "a/b"]
    assert _hoist(["--root", "X", "hook", "session-start"]) == \
        ["hook", "session-start", "--root", "X"]
    assert _hoist(["find", "x", "--root", "X"]) == ["find", "x", "--root", "X"]  # untouched
    assert _hoist(["--help"]) == ["--help"]


def test_flags_in_either_position_reach_the_command(fx: Fixture):
    for argv in (("--root", str(fx.store), "find", "nightly"),
                 ("find", "nightly", "--root", str(fx.store))):
        rc, out, err = run(mem_cmd(*argv), fx.env())
        assert rc == 0, err
        assert "lab-backup-plan" in out


def test_top_level_help_lists_every_command(fx: Fixture):
    rc, out, _ = run(mem_cmd("--help"), fx.env())
    assert rc == 0
    for cmd in ("find", "show", "new", "verified", "supersede", "audit", "link", "render",
                "commit", "fix"):
        assert f"mem {cmd}" in out


def test_audit_commands_have_their_own_help_and_flags(fx: Fixture):
    rc, out, _ = run(mem_cmd("link", "--help"), fx.env())
    assert rc == 0 and out.startswith("usage: mem link") and "--territory" in out
    assert "make the link" in out and "fix: apply" not in out
    rc, out, _ = run(mem_cmd("audit", "--help"), fx.env())
    assert out.startswith("usage: mem audit") and "--refine" in out and "--stamp-today" not in out
    rc, _, err = run(mem_cmd("audit", "--stamp-today"), fx.env())
    assert rc == 2 and "unrecognized" in err


def test_an_unknown_command_says_where_the_list_is(fx: Fixture):
    rc, _, err = run(mem_cmd("cards/cairn"), fx.env())
    assert rc == 2 and "unknown command 'cards/cairn'" in err and "mem --help" in err


def test_show_a_territory_prints_its_index(fx: Fixture):
    idx = fx.store / "territories/home/lab/MEMORY.md"
    for spec in ("home/lab", "territories/home/lab", "territories/home/lab/MEMORY.md"):
        rc, out, err = run(mem_cmd("show", spec), fx.env())
        assert rc == 0, err
        assert out.startswith(f"home/lab  {idx}\n") and idx.read_text() in out
    rc, _, err = run(mem_cmd("show", "home/nowhere"), fx.env())
    assert rc == 2 and "no memory or territory" in err


def test_find_with_only_a_territory_points_at_show(fx: Fixture):
    rc, _, err = run(mem_cmd("find", "--territory", "home/lab"), fx.env())
    assert rc == 2 and "`mem show home/lab`" in err


def test_the_hook_takes_root(fx: Fixture, tmp_path: Path):
    rc, out, _ = run(mem_cmd("hook", "session-start", "--root", str(tmp_path / "none")),
                     fx.env())
    assert rc == 0
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert f"no store at `{tmp_path / 'none'}`" in ctx


def _territory(store: Path, t: str, head: str, body: str) -> None:
    d = store / "territories" / t
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text(f"---\nterritory: {t}\n{head}---\n# {t}\n\n{body}\n")


def test_guess_territory_prefers_members_then_mentions(tmp_path: Path):
    store = tmp_path / "store"
    _territory(store, "console/tools", "", "The retrotink scaler. retrotink again.")
    _territory(store, "home/lab", "members:\n  retrotink-flasher: {owner: self, mode: parked}\n",
               "Nothing about it here.")
    _territory(store, "solo/other", "", "Unrelated.")
    all_t = ["console/tools", "home/lab", "solo/other"]
    t, why = guess_territory(store, tmp_path / "retrotink-flasher", all_t)
    assert t == "home/lab" and "members" in why                  # a parked repo, cloned back
    t, why = guess_territory(store, tmp_path / "retrotink-mk2", all_t[::2])
    assert t == "console/tools" and "`retrotink` 2x" in why      # longest name part
    assert guess_territory(store, tmp_path / "zzz", all_t) is None


def test_the_no_territory_note_names_the_link_command(fx: Fixture, tmp_path: Path):
    repo = tmp_path / "lab-backup-tool"
    (repo / ".git").mkdir(parents=True)
    rc, out, _ = run(mem_cmd("hook", "session-start"), fx.env(cwd=repo))
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "maps to NO territory" in ctx and "docs/setup.md step 5" not in ctx
    assert "`mem link --territory " in ctx and "--write`" in ctx
