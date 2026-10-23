"""Rendered territory indexes (direction §6, Phase 4): adoption, render, check, and the hook."""
from __future__ import annotations

import json
import subprocess

from conftest import Fixture, hook_cmd, mem_cmd, run
from test_storegit import git, init

from claude_hybrid_memory import render
from claude_hybrid_memory.store import parse_frontmatter

KIT = "territories/console/kit"


def grouped(fx: Fixture) -> None:
    """console/kit's index as console/tools writes one: headings over the entries, and a
    prose line inside the section that a render cannot keep."""
    p = fx.store / KIT / "MEMORY.md"
    head = p.read_text().split("## MEMORIES")[0]
    p.write_text(head + "## MEMORIES\n\n"
                 "### Sync\n"
                 "- [Sync design](kit-sync-design.md) — start here; the v1 notes are history.\n"
                 "- [Sync v1](kit-sync-v1.md) — the first cut.\n\n"
                 "### Bench work\n"
                 "- [Fodder corpus](kit-fodder-corpus.md) — HISTORICAL test corpus.\n"
                 "- [Gone file](kit-gone-file.md) — listed, but deleted.\n"
                 "- [Raw notes](kit_raw_notes.md) — SHIPPED raw notes from the bench.\n\n"
                 "Ask Matt before adding a group.\n")


def test_adopt_dry_run_reports_and_writes_nothing(fx: Fixture):
    grouped(fx)
    before = {p: p.read_bytes() for p in (fx.store / KIT).glob("*.md")}
    a = render.adopt(fx.store, "console/kit")
    assert {p: p.read_bytes() for p in (fx.store / KIT).glob("*.md")} == before
    assert a.groups == ["Sync", "Bench work"]
    assert a.ghosts == ["kit-gone-file.md"]
    assert a.superseded == ["kit-sync-v1"]
    assert a.prose == ["Ask Matt before adding a group."]
    assert sorted(a.unlisted) == ["kit-bad-recipe", "kit-unlisted-orphan"]
    by = {ln.slug: ln for ln in a.lines}
    # "the v1 notes are history" is judgment the description does not carry; "design" is
    # in the slug, which the rendered line shows
    assert by["kit-sync-design"].missing == ["notes", "history"]
    assert by["kit_raw_notes"].missing == []
    assert a.compact == ["kit-fodder-corpus"]


def test_adopt_write_renders_and_keeps_the_hand_written_head(fx: Fixture):
    grouped(fx)
    idx = fx.store / KIT / "MEMORY.md"
    head = idx.read_text().split("---\n# console/kit")[1].split("## MEMORIES")[0]
    rc, out, err = run(mem_cmd("render", "console/kit", "--adopt", "--write"), fx.env())
    assert rc == 0, err
    text = idx.read_text()
    assert head in text
    meta, _, problems = parse_frontmatter(text)
    assert meta["groups"] == ["Sync", "Bench work"] and not problems
    assert meta["consumes"] == "home/lab"
    s, e = render.markers(text)
    assert text[s:e] == (
        "### Sync\n"
        "- [kit-sync-design](kit-sync-design.md) — The current sync architecture; start here.\n"
        "### Bench work\n"
        "- [kit_raw_notes](kit_raw_notes.md) — SHIPPED raw notes from the bench.\n"
        "- Records and history: [kit-fodder-corpus](kit-fodder-corpus.md)\n"
        "### Other\n"
        "- [kit-bad-recipe](kit-bad-recipe.md) — A recipe that pipes.\n"
        "- [kit-unlisted-orphan](kit-unlisted-orphan.md) — Nothing links here and no router "
        "lists it.\n")
    m, _, _ = parse_frontmatter((fx.store / KIT / "kit-fodder-corpus.md").read_text())
    assert m["group"] == "Bench work"
    # the superseded file is never edited, so it gets no group either
    assert "group:" not in (fx.store / KIT / "kit-sync-v1.md").read_text()
    assert render.check(fx.store, ["console/kit"]) == []
    rc, _, err = run(mem_cmd("render", "console/kit", "--adopt"), fx.env())
    assert rc == 2 and "already rendered" in err


def test_a_changed_description_is_stale_until_rendered(fx: Fixture):
    grouped(fx)
    render.write_adoption(fx.store, render.adopt(fx.store, "console/kit"))
    p = fx.store / KIT / "kit-sync-design.md"
    p.write_text(p.read_text().replace("start here.", "start here; v1 is history."))
    [f] = render.check(fx.store)
    assert f.code == "render-stale"
    rc, out, _ = run(mem_cmd("render", "--check"), fx.env())
    assert rc == 0 and "render-stale" in out
    rc, out, _ = run(mem_cmd("render"), fx.env())
    assert rc == 0 and "console/kit: re-rendered" in out
    assert "start here; v1 is history." in (fx.store / KIT / "MEMORY.md").read_text()
    assert render.check(fx.store) == []


def test_the_memories_section_is_budgeted_on_every_index(fx: Fixture):
    lab = fx.store / "territories/home/lab/MEMORY.md"
    base = lab.read_text()
    lab.write_text(base + "- line\n" * 100)
    [f] = render.check(fx.store)
    assert (f.level, f.code) == ("warn", "memories-over-target")
    lab.write_text(base + "- line\n" * 150)
    [f] = render.check(fx.store)
    assert (f.level, f.code) == ("error", "memories-over-cap")
    rc, _, _ = run(mem_cmd("render", "--check"), fx.env())
    assert rc == 1


def test_the_head_is_not_budgeted_but_the_harness_cap_still_is(fx: Fixture):
    lab = fx.store / "territories/home/lab/MEMORY.md"
    base = lab.read_text()
    head = base.replace("## MEMORIES", "gate\n" * 120 + "## MEMORIES")
    lab.write_text(head)
    assert render.check(fx.store) == []
    lab.write_text(head + "- line\n" * 90)
    [f] = render.check(fx.store)
    assert (f.level, f.code) == ("error", "index-over-cap")


def test_superseded_and_dropped_is_not_unlisted_or_orphaned(fx: Fixture):
    grouped(fx)
    render.write_adoption(fx.store, render.adopt(fx.store, "console/kit"))
    rc, out, _ = run(mem_cmd("audit", "--json", "--scan", "store"), fx.env())
    found = {(f["code"], f["path"].rsplit("/", 1)[-1]) for f in json.loads(out)}
    assert ("router-unlisted", "kit-sync-v1.md") not in found
    assert ("orphan", "kit-sync-v1.md") not in found
    assert ("superseded-still-indexed", "MEMORY.md") not in found


def test_session_end_renders_before_it_commits(fx: Fixture):
    grouped(fx)
    render.write_adoption(fx.store, render.adopt(fx.store, "console/kit"))
    init(fx.store)
    p = fx.store / KIT / "kit-sync-design.md"
    p.write_text(p.read_text().replace("start here.", "start here, always."))
    subprocess.run(hook_cmd()[:-1] + ["session-end"], input="{}", text=True, env=fx.env(),
                   timeout=30, check=True)
    assert git(fx.store, "status", "--porcelain") == ""
    assert "start here, always." in git(fx.store, "show", f"HEAD:{KIT}/MEMORY.md")


def test_render_refuses_a_territory_not_yet_adopted(fx: Fixture):
    rc, _, err = run(mem_cmd("render", "console/kit"), fx.env())
    assert rc == 2 and "--adopt" in err
    rc, _, err = run(mem_cmd("render", "console/kit", "--write"), fx.env())
    assert rc == 2


def test_uncovered_reads_hyphens_both_ways():
    assert render.uncovered("the keep-list stem trap", "keep list, stem traps") == []
    assert render.uncovered("keep list", "the keep-list") == []
    assert render.uncovered("DONE 2026-09-03", "closed 2026-09-03") == ["done"]


def test_a_long_description_is_cut_on_its_line_and_whole_in_its_file():
    assert render.clip("short enough") == "short enough"
    long = "word " * 60
    cut = render.clip(long)
    assert cut.endswith("word…") and len(cut.encode()) <= render.LINE_DESC
    assert render.clip("alpha beta, gamma delta", 14) == "alpha beta…"
    # bytes, not characters, and never half a character
    assert render.clip("é" * 100, 11) == "é" * 4 + "…"
    assert render.clip("x" * 50, 10) == "x" * 7 + "…"


def test_the_byte_cap_warns_a_kilobyte_early(fx: Fixture):
    lab = fx.store / "territories/home/lab/MEMORY.md"
    base = lab.read_text()
    head = base.replace("## MEMORIES", ("g" * 199 + "\n") * 121 + "## MEMORIES")
    lab.write_text(head)
    [f] = render.check(fx.store)
    assert (f.level, f.code) == ("warn", "index-near-cap")
