"""Rendered territory indexes (direction §6, Phase 4): adoption, render, check, and the hook."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
    p.write_text(
        head + "## MEMORIES\n\n"
        "### Sync\n"
        "- [Sync design](kit-sync-design.md) — start here; the v1 notes are history.\n"
        "- [Sync v1](kit-sync-v1.md) — the first cut.\n\n"
        "### Bench work\n"
        "- [Fodder corpus](kit-fodder-corpus.md) — HISTORICAL test corpus.\n"
        "- [Gone file](kit-gone-file.md) — listed, but deleted.\n"
        "- [Raw notes](kit_raw_notes.md) — SHIPPED raw notes from the bench.\n\n"
        "Ask Matt before adding a group.\n"
    )


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
        "Each name below is `<name>.md` beside this file.\n"
        "### Sync\n"
        "- kit-sync-design: The current sync architecture; start here.\n"
        "### Bench work\n"
        "- kit_raw_notes: SHIPPED raw notes from the bench.\n"
        "- Records: kit-fodder-corpus\n"
        "### Other\n"
        "- kit-bad-recipe: A recipe that pipes.\n"
        "- kit-unlisted-orphan: Nothing links here and no router lists it.\n"
    )
    m, _, _ = parse_frontmatter((fx.store / KIT / "kit-fodder-corpus.md").read_text())
    assert m["group"] == "Bench work"
    # the superseded file is never edited, so it gets no group either
    assert "group:" not in (fx.store / KIT / "kit-sync-v1.md").read_text()
    # the two in Other have no group: refine items, nothing else
    assert {(f.code, Path(f.path).name) for f in render.check(fx.store, ["console/kit"])} == {
        ("field-invalid", "kit-bad-recipe.md"),
        ("field-invalid", "kit-unlisted-orphan.md"),
    }
    rc, _, err = run(mem_cmd("render", "console/kit", "--adopt"), fx.env())
    assert rc == 2 and "already rendered" in err


def test_a_changed_description_is_stale_until_rendered(fx: Fixture):
    grouped(fx)
    render.write_adoption(fx.store, render.adopt(fx.store, "console/kit"))
    p = fx.store / KIT / "kit-sync-design.md"
    p.write_text(p.read_text().replace("start here.", "start here; v1 is history."))
    [f] = [f for f in render.check(fx.store) if f.code != "field-invalid"]
    assert f.code == "render-stale"
    rc, out, _ = run(mem_cmd("render", "--check"), fx.env())
    assert rc == 0 and "render-stale" in out
    rc, out, _ = run(mem_cmd("render"), fx.env())
    assert rc == 0 and "console/kit: re-rendered" in out
    assert "start here; v1 is history." in (fx.store / KIT / "MEMORY.md").read_text()
    assert [f for f in render.check(fx.store) if f.code != "field-invalid"] == []


def test_the_memories_section_is_budgeted_on_every_index(fx: Fixture):
    lab = fx.store / "territories/home/lab/MEMORY.md"
    base = lab.read_text()
    lab.write_text(base + "- line\n" * 100)
    [f] = render.check(fx.store)
    assert (f.level, f.code) == ("info", "memories-over-target")
    lab.write_text(base + "- line\n" * 150)
    [f] = render.check(fx.store)
    assert (f.level, f.code) == ("warn", "memories-over-cap")
    # size never fails a command: it is the refine pass's to act on
    rc, out, _ = run(mem_cmd("render", "--check"), fx.env())
    assert rc == 0 and "memories-over-cap" in out
    rc, out, _ = run(mem_cmd("audit"), fx.env())
    assert "memories-over-cap" not in out
    rc, out, _ = run(mem_cmd("audit", "--refine"), fx.env())
    assert "memories-over-cap" in out


def test_the_head_is_not_budgeted_but_the_harness_cap_still_is(fx: Fixture):
    lab = fx.store / "territories/home/lab/MEMORY.md"
    base = lab.read_text()
    head = base.replace("## MEMORIES", "gate\n" * 120 + "## MEMORIES")
    lab.write_text(head)
    assert render.check(fx.store) == []
    lab.write_text(head + "- line\n" * 90)
    [f] = render.check(fx.store)
    assert (f.level, f.code) == ("warn", "index-over-cap")


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
    subprocess.run(
        hook_cmd()[:-1] + ["session-end"],
        input="{}",
        text=True,
        env=fx.env(),
        timeout=30,
        check=True,
    )
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
    assert (f.level, f.code) == ("info", "index-near-cap")


def test_an_appended_pointer_is_taken_into_the_section(fx: Fixture):
    """The harness's auto-memory writes a file, then appends its pointer to MEMORY.md, which
    in an adopted index lands below the end marker (cbz-tagger, 2026-10-23)."""
    grouped(fx)
    render.write_adoption(fx.store, render.adopt(fx.store, "console/kit"))
    (fx.store / KIT / "kit-new-probe.md").write_text(
        "---\nname: kit-new-probe\ndescription: The probe says it works.\nmetadata:\n"
        "  type: project\n---\n\nBody.\n"
    )
    index = fx.store / KIT / "MEMORY.md"
    index.write_text(
        index.read_text() + "- [kit-new-probe](kit-new-probe.md) — hand line\n"
        "- [elsewhere](../other.md) — not ours, kept\n"
    )
    codes = {(f.code, Path(f.path).name) for f in render.check(fx.store)}
    assert ("index-hand-entry", "kit-new-probe.md") in codes
    assert ("router-count", "ROUTER.md") in codes  # console/kit (6) -> 7
    rc, _, _ = run(mem_cmd("render"), fx.env())
    assert rc == 0
    text = index.read_text()
    assert text.count("kit-new-probe") == 1 and "hand line" not in text
    assert text.index("- kit-new-probe: ") < text.index(render.END)
    assert "not ours, kept" in text
    assert "- console/kit (7) :" in (fx.store / "ROUTER.md").read_text()
    assert [f for f in render.check(fx.store) if f.code != "field-invalid"] == []


def test_every_territory_is_on_the_map_and_every_memory_in_its_index(fx: Fixture):
    (fx.store / "territories/home/attic").mkdir()
    (fx.store / "territories/home/attic/MEMORY.md").write_text("# home/attic\n\n## MEMORIES\n")
    rc, out, _ = run(mem_cmd("audit", "--json", "--scan", "store"), fx.env())
    found = {(f["level"], f["code"], "/".join(f["path"].split("/")[-2:])) for f in json.loads(out)}
    assert rc == 1
    assert ("error", "router-missing-territory", "attic/MEMORY.md") in found
    assert ("error", "router-unlisted", "kit/kit-unlisted-orphan.md") in found


def test_the_map_and_consumes_name_only_real_or_planned_territories(fx: Fixture):
    router = fx.store / "ROUTER.md"
    router.write_text(
        router.read_text()
        + "- home/gone (3) : renamed away, line left behind.\n"
        + "- console/next, console/later : NOT YET WRITTEN.\n"
        + "  The plan.\n"
    )
    lab = fx.store / "territories/home/lab/MEMORY.md"
    # a glob is fine while it matches something
    refs = "console/kit, console/next, home/old, home/*, attic/*"
    lab.write_text(lab.read_text().replace("consumed_by: console/kit", f"consumed_by: {refs}"))
    checked = render.check_router(fx.store)
    found = {(f.level, f.code, f.message.split(",")[0].split(" ")[0]) for f in checked}
    assert ("error", "router-unknown-territory", "home/gone") in found
    assert ("info", "router-planned-territory", "console/next") in found
    assert ("info", "router-planned-territory", "console/later") in found
    assert ("info", "territory-ref-planned", "consumed_by:") in found
    unknown = [f.message.split(",")[0] for f in checked if f.code == "territory-ref-unknown"]
    assert unknown == ["consumed_by: home/old", "consumed_by: attic/*"]
    assert not any(
        f.code == "router-unknown-territory" and "home/lab" in f.message for f in checked
    )


def test_router_entries_reads_lists_counts_and_continuations():
    text = (
        "## home\n- home/a, home/B-c (2) : one.\n  more.\n- home/d : two.\n\n"
        "## EXPORTS\n- [lab-policy] not an entry\n"
    )
    e = render.router_entries(text)
    assert sorted(e) == ["home/B-c", "home/a", "home/d"]
    assert e["home/a"].endswith("more.") and e["home/d"] == "- home/d : two."


def test_index_entry_reads_both_forms_and_index_names_reads_lists():
    from claude_hybrid_memory.spec import index_entry, index_names

    assert index_entry("- [Title](a-b.md) — gloss") == ("a-b.md", "Title", "gloss")
    assert index_entry("- a-b: gloss: more") == ("a-b.md", "a-b", "gloss: more")
    assert index_entry("- Records: a b") is None
    assert index_entry("- **bold**: prose") is None
    assert index_names("- [T](x.md) — g\n- y: g\n- Records: r1 r2\n- Names: n1\n") == {
        "x.md",
        "y.md",
        "r1.md",
        "r2.md",
        "n1.md",
    }


def crowd(fx: Fixture, n: int, desc_bytes: int = 150) -> list[Path]:
    """console/kit adopted, plus `n` grouped memories with descriptions of `desc_bytes`:
    a console/tools-sized index made in bulk, never copied from the real store."""
    grouped(fx)
    render.write_adoption(fx.store, render.adopt(fx.store, "console/kit"))
    out = []
    for i in range(n):
        g = ("Sync", "Bench work")[i % 2]
        desc = (f"Memory {i} " + "word " * 60)[:desc_bytes].strip()
        p = fx.store / KIT / f"kit-crowd-{i:03d}.md"
        p.write_text(
            f'---\nname: kit-crowd-{i:03d}\ndescription: "{desc}"\n'
            f'group: "{g}"\n' + ("tier: record\n" if i % 7 == 0 else "") + "---\n\nBody.\n"
        )
        out.append(p)
    return out


def test_render_steps_down_to_fit_and_never_touches_a_description(fx: Fixture):
    files = crowd(fx, 170)
    before = {p: p.read_bytes() for p in files}
    rc, out, _ = run(mem_cmd("render", "console/kit"), fx.env())
    assert rc == 0 and "kit" in out
    text = (fx.store / KIT / "MEMORY.md").read_text()
    assert len(text.encode()) <= render.BYTE_TARGET and render.nlines(text) <= render.LINE_TARGET
    assert {p: p.read_bytes() for p in files} == before
    codes = {(f.level, f.code) for f in render.check(fx.store, ["console/kit"])}
    assert ("info", "index-degraded") in codes
    assert not any(level == "error" for level, _ in codes)
    # a writing session's audit says nothing about it, and nothing is "unlisted"
    rc, out, _ = run(mem_cmd("audit", "--scan", "store"), fx.env())
    assert "index-degraded" not in out and "router-unlisted" not in out
    rc, out, _ = run(mem_cmd("audit", "--scan", "store", "--refine"), fx.env())
    assert "index-degraded" in out


def test_the_ladder_is_mildest_first(fx: Fixture):
    crowd(fx, 60)
    t = render.load(fx.store, "console/kit")
    steps = list(render.ladder(t))
    assert steps[0].none and [s.desc for s in steps[:3]] == [160, 120, 80]
    # a line step is tried with full descriptions first, since cutting saves no lines
    assert [(s.records, s.desc) for s in steps[3:7]] == [
        ("one", 160),
        ("one", 120),
        ("one", 80),
        ("none", 160),
    ]
    # groups collapse from the bottom of the index up: Other first, then groups: in reverse
    assert steps[9].names_only == (None,) and steps[12].names_only == (None, "Bench work")
    # a territory that fits is not degraded at all
    _, _, d, _ = render.render_full(fx.store, "console/kit", False)
    assert d.none


def test_a_long_description_is_a_refine_item(fx: Fixture):
    p = crowd(fx, 2, 0)[1]  # [0] is a record, which gets no description line
    p.write_text(p.read_text().replace('description: ""', 'description: "' + "x " * 120 + '"'))
    render.render(fx.store, "console/kit")
    [f] = [f for f in render.check(fx.store) if f.code == "description-long"]
    assert f.level == "info" and f.path.endswith("kit-crowd-001.md")
