"""Version chains (direction §6, Phase 3): `supersedes:` on the newer memory, inverse derived."""
from __future__ import annotations

import json
import subprocess

from conftest import Fixture, mem_cmd, run
from test_post_tool import post

from claude_hybrid_memory import cache, chains, events
from claude_hybrid_memory.chains import Node

V1 = "territories/console/kit/kit-sync-v1.md"
DESIGN = "territories/console/kit/kit-sync-design.md"


def n(path, refs=(), area="territory"):
    container, _, file = path.rpartition("/")
    return Node(path, area, container, file.removesuffix(".md"), tuple(refs))


def codes(g):
    return sorted(f.code for f in g.findings)


# --- the graph ----------------------------------------------------------------------------

def test_refs_take_every_yaml_form():
    assert chains.refs_of({"supersedes": "a"}) == ("a",)
    assert chains.refs_of({"supersedes": ["a", " b ", ""]}) == ("a", "b")
    assert chains.refs_of({"supersedes": None}) == chains.refs_of({}) == ()


def test_bare_slug_prefers_its_own_container_and_otherwise_is_ambiguous():
    nodes = [n("t/a/new.md", ["dup"]), n("t/a/dup.md"), n("t/b/dup.md"), n("t/c/x.md", ["dup"])]
    g = chains.build(nodes)
    assert g.older == {"t/a/new.md": ["t/a/dup.md"]}
    assert codes(g) == ["supersede-ambiguous"]
    assert chains.build([n("t/c/x.md", ["t/b/dup"]), *nodes[1:3]]).older == \
        {"t/c/x.md": ["t/b/dup.md"]}


def test_self_gone_and_cycles_are_reported():
    g = chains.build([n("t/a/s.md", ["s"]), n("t/a/g.md", ["never-existed"]),
                      n("t/a/x.md", ["y"]), n("t/a/y.md", ["z"]), n("t/a/z.md", ["x"])])
    assert codes(g) == ["supersede-cycle", "supersede-self", "supersede-target-gone"]
    [cyc] = [f for f in g.findings if f.code == "supersede-cycle"]
    assert cyc.message.count("->") == 3
    assert g.superseded() == {"t/a/x.md", "t/a/y.md", "t/a/z.md"}


def test_a_successor_retired_to_archive_hides_nothing():
    g = chains.build([n("t/a/old.md"), n("archive/g/new.md", ["t/a/old"], area="archive")])
    assert g.older and g.superseded() == set()


def test_walk_goes_both_ways_and_shows_dead_ends():
    g = chains.build([n("t/a/v1.md", ["v0"]), n("t/a/v2.md", ["v1"]), n("t/a/v3.md", ["v2"])])
    back = [(d, x.slug if x else note) for d, x, note in chains.walk(g, "t/a/v3.md", "older")]
    assert back == [(1, "v2"), (2, "v1"), (3, "v0 (not found)")]
    fwd = [(d, x.slug) for d, x, _ in chains.walk(g, "t/a/v1.md", "newer")]
    assert fwd == [(1, "v2"), (2, "v3")]


def test_with_refs_rewrites_only_the_supersedes_line():
    block = "---\nname: a\nsupersedes:\n  - x\ndescription: d\nmetadata:\n  k: v\n---\nbody\n"
    assert chains.with_refs(block, ["x", "y"]) == \
        "---\nname: a\ndescription: d\nmetadata:\n  k: v\nsupersedes: [x, y]\n---\nbody\n"
    assert chains.with_refs("---\nname: a\n---\n", ["q", "q"]) == \
        "---\nname: a\nsupersedes: q\n---\n"


# --- the cache ------------------------------------------------------------------------------

def test_find_hides_superseded_counts_them_and_names_the_successor(fx: Fixture):
    conn = cache.connect(fx.store)
    cache.refresh(conn, fx.store)
    found = cache.find(conn, ["first", "sync", "cut"])
    assert found.hits == [] and found.superseded_hidden == 1
    [h] = cache.find(conn, ["first", "sync", "cut"], include_superseded=True).hits
    assert h.slug == "kit-sync-v1" and h.superseded_by == ["console/kit/kit-sync-design"]


def test_chains_follow_edits_and_deletes(fx: Fixture):
    conn = cache.connect(fx.store)
    cache.refresh(conn, fx.store)
    design = fx.store / DESIGN
    design.write_text(design.read_text().replace("supersedes: kit-sync-v1\n", ""))
    cache.refresh(conn, fx.store)
    assert cache.find(conn, ["first", "sync", "cut"]).hits
    design.write_text(design.read_text().replace("---\n\n", "supersedes: kit-sync-v1\n---\n\n", 1))
    cache.refresh(conn, fx.store)
    assert not cache.find(conn, ["first", "sync", "cut"]).hits
    design.unlink()
    cache.refresh(conn, fx.store)
    assert cache.find(conn, ["first", "sync", "cut"]).hits


def test_audit_and_cache_derive_the_same_graph(fx: Fixture):
    from claude_hybrid_memory.audit.relations import store_graph
    conn = cache.connect(fx.store)
    cache.refresh(conn, fx.store)
    assert cache.graph(conn).older == store_graph(fx.store).older == {DESIGN: [V1]}


# --- the CLI ---------------------------------------------------------------------------------

def mem(fx: Fixture, *args):
    return run(mem_cmd(*args, "--root", str(fx.store)), fx.env())


def test_supersede_writes_the_newer_file_only_and_logs_it(fx: Fixture):
    old, new = fx.store / "territories/home/lab/lab-backup-plan.md", \
        fx.store / "territories/home/lab/lab-ssh-read-only.md"
    before = old.read_bytes()
    rc, out, _ = mem(fx, "supersede", "lab-backup-plan", "lab-ssh-read-only")
    assert rc == 0 and "home/lab/lab-ssh-read-only now supersedes home/lab/lab-backup-plan" in out
    assert "MEMORY.md still lists lab-backup-plan.md" in out
    assert old.read_bytes() == before
    assert "\nsupersedes: lab-backup-plan\n---" in new.read_text()
    [e] = list(events.read_all(fx.store))
    assert (e["event"], e["path"], e["tool"]) == ("write", str(new.relative_to(fx.store)),
                                                  "mem supersede")
    rc, out, _ = mem(fx, "supersede", "lab-backup-plan", "lab-ssh-read-only")
    assert rc == 0 and "already supersedes" in out
    rc, _, err = mem(fx, "supersede", "lab-ssh-read-only", "lab-backup-plan")
    assert rc == 2 and "loop" in err


def test_supersede_appends_to_an_existing_ref_and_refuses_archive_as_the_newer(fx: Fixture):
    rc, _, _ = mem(fx, "supersede", "kit-fodder-corpus", "kit-sync-design")
    assert rc == 0
    assert "supersedes: [kit-sync-v1, kit-fodder-corpus]" in (fx.store / DESIGN).read_text()
    rc, _, err = mem(fx, "supersede", "kit-sync-v1", "kit-legacy-sync")
    assert rc == 2 and "archive" in err


def test_history_shows_both_directions_and_the_git_log(fx: Fixture):
    subprocess.run(["git", "init", "-q", str(fx.store)], check=True)
    subprocess.run(["git", "-C", str(fx.store), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qam", "baseline", "--allow-empty"], check=True)
    subprocess.run(["git", "-C", str(fx.store), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(fx.store), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "fixture store"], check=True)
    rc, out, _ = mem(fx, "history", "kit-sync-v1")
    assert rc == 0 and "SUPERSEDED" in out
    assert out.index("Superseded by (newer):") < out.index("console/kit/kit-sync-design")
    assert "fixture store" in out
    rc, out, _ = mem(fx, "history", "kit-sync-design", "--json")
    h = json.loads(out)
    assert not h["superseded"] and [r["key"] for r in h["older"]] == ["console/kit/kit-sync-v1"]
    assert h["newer"] == [] and h["commits"][0]["subject"] == "fixture store"


def test_show_and_find_say_superseded(fx: Fixture):
    rc, out, _ = mem(fx, "show", "kit-sync-v1")
    assert rc == 0 and "SUPERSEDED by console/kit/kit-sync-design" in out
    rc, out, _ = mem(fx, "find", "first", "sync", "cut")
    assert "no matches" in out and "1 match superseded not shown (--superseded)" in out
    rc, out, _ = mem(fx, "find", "first", "sync", "cut", "--superseded")
    assert "SUPERSEDED by console/kit/kit-sync-design" in out


# --- the hook: split when next touched --------------------------------------------------------

def test_editing_an_accreted_file_suggests_a_split_once_per_session(fx: Fixture):
    p = fx.store / "territories/home/lab/lab-backup-plan.md"
    cache.refresh(cache.connect(fx.store), fx.store)  # the file is known, not new
    p.write_text(p.read_text() + "\n**CORRECTION 2026-10-01:** weekly, not nightly.\n")
    rc, out = post(fx, "Edit", p, session="s1")
    assert rc == 0 and "tier: record" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert post(fx, "Edit", p, session="s1") == (0, "")
    assert post(fx, "Edit", p, session="s2")[1]
