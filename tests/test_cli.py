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


# --- P3 polish from the same eval -------------------------------------------------------

def test_show_says_how_much_it_left_out(fx: Fixture):
    rc, out, _ = run(mem_cmd("show", "lab-backup-plan"), fx.env())
    assert rc == 0 and "more lines: `--full` for all" in out and "Current · History" in out


def test_show_meta_lists_what_links_here(fx: Fixture):
    rc, out, _ = run(mem_cmd("show", "--meta", "lab-ssh-read-only"), fx.env())
    assert "linked from (2):" in out
    assert "territories/home/lab/MEMORY.md:" in out
    assert "territories/console/kit/kit-sync-design.md:" in out


def test_render_check_names_an_unrendered_territory(fx: Fixture):
    rc, out, _ = run(mem_cmd("render", "home/lab", "--check"), fx.env())
    assert "index-not-rendered" in out and "mem render home/lab --adopt" in out


def test_log_takes_a_territory_or_a_slug_and_refuses_a_typo(fx: Fixture):
    import subprocess
    subprocess.run(["git", "init", "-q", str(fx.store)], check=True)
    subprocess.run(["git", "-C", str(fx.store), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(fx.store), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "baseline"], check=True)
    for spec in ("home/lab", "lab-backup-plan", "territories/home/lab"):
        rc, out, err = run(mem_cmd("log", spec), fx.env())
        assert rc == 0 and "baseline" in out, (spec, err)
    rc, _, err = run(mem_cmd("log", "home/nowhere"), fx.env())
    assert rc == 2 and "no store path, territory or memory 'home/nowhere'" in err


def test_new_keeps_the_router_count_true(fx: Fixture):
    import subprocess
    p = subprocess.run(mem_cmd("new", "lab-probe", "-t", "home/lab", "-v", "slow", "-d", "x"),
                       input="Body.\n", capture_output=True, text=True, env=fx.env())
    assert p.returncode == 0, p.stderr
    real = len(list((fx.store / "territories/home/lab").glob("*.md"))) - 2  # MEMORY, EXPORTS
    assert f"- home/lab ({real}) :" in (fx.store / "ROUTER.md").read_text()
    rc, out, _ = run(mem_cmd("audit", "--json", "-t", "home/lab"), fx.env())
    assert not [f for f in json.loads(out) if f["code"] == "router-count"]


def test_audit_scopes_to_a_territory(fx: Fixture):
    rc, out, _ = run(mem_cmd("audit", "--json", "-t", "console/kit"), fx.env())
    paths = [f["path"] for f in json.loads(out)]
    assert paths and all("/territories/console/kit" in p for p in paths)
    rc, _, err = run(mem_cmd("audit", "-t", "console/nowhere"), fx.env())
    assert rc == 2 and "no territory" in err


def test_link_under_a_scratch_root_needs_legacy_too(fx: Fixture, tmp_path: Path):
    import shutil
    scratch = tmp_path / "scratch"
    shutil.copytree(fx.store, scratch)
    env = fx.env()
    env["HOME"] = str(fx.home)
    rc, _, err = run(mem_cmd("link", "-t", "home/lab", "--root", str(scratch), "--write"), env)
    assert rc == 2 and "pass --legacy too" in err
    rc, _, err = run(mem_cmd("link", "-t", "home/lab", "--root", str(scratch),
                             "--legacy", str(tmp_path / "projects"), "--write"), env)
    assert rc == 0, err


def test_cwd_territory_resolves_inside_a_scratch_root(fx: Fixture, tmp_path: Path):
    # fx.repo's silo points into fx.store; under --root a copy, `mem new` must land in the
    # copy's territory, not fail to map (eval 2026-11-04) or write the original.
    import shutil
    import subprocess
    scratch = tmp_path / "scratch"
    shutil.copytree(fx.store, scratch)
    p = subprocess.run(mem_cmd("new", "kit-probe", "-v", "slow", "-d", "x", "--root",
                               str(scratch)), input="Body.\n", capture_output=True,
                       text=True, env=fx.env(), cwd=fx.repo)
    assert p.returncode == 0, p.stderr
    assert (scratch / "territories/console/kit/kit-probe.md").is_file()
    assert not (fx.store / "territories/console/kit/kit-probe.md").exists()
