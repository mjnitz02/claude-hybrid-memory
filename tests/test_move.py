"""`mem mv-territory`: a rename or an area move touches everything that names the territory,
in one store commit, and leaves no silo pointing at nothing."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import Fixture, mem_cmd, run
from test_storegit import git, init

from claude_hybrid_memory import move
from claude_hybrid_memory.migrate import apply
from claude_hybrid_memory.migrate import plan as P


def moved(fx: Fixture, old: str, new: str) -> list:
    mv = move.plan_territory(fx.store, fx.projects, old, new)
    assert isinstance(mv, move.Move), mv
    return move.apply_territory(fx.store, fx.projects, mv)


@pytest.fixture
def store(fx: Fixture) -> Fixture:
    # a cross-territory version-chain ref, which names the container
    (fx.store / "territories/home/lab/lab-sync-notes.md").write_text(
        "---\nname: lab-sync-notes\nkind: territory\nsupersedes: console/kit/kit-fodder-corpus\n"
        "description: Sync notes kept on the lab side.\nstatus: SHIPPED\n"
        "last_verified: 2026-10-01\n---\n\nSee `console/kit` for the tools.\n")
    init(fx.store)
    return fx


def test_an_area_move_rewrites_everything_that_names_it(store: Fixture):
    fx = store
    out = moved(fx, "console/kit", "shop/kit")
    codes = {f.code for f in out}
    assert "mv-committed" in codes and "mv-new-error" not in codes, out

    t = fx.store / "territories"
    assert not (t / "console").exists() and (t / "shop/kit/kit-sync-design.md").is_file()
    index = (t / "shop/kit/MEMORY.md").read_text()
    assert "territory: shop/kit\n" in index and "\n# shop/kit\n" in index

    # the silo follows, so the repo still loads its territory
    link = next(p for p in fx.projects.glob("*/memory") if p.is_symlink())
    assert Path(os.path.realpath(link)) == (t / "shop/kit").resolve()

    # refs in other territories' frontmatter follow; prose is reported, not rewritten
    lab = (t / "home/lab/MEMORY.md").read_text()
    assert "consumed_by: shop/kit" in lab
    notes = (t / "home/lab/lab-sync-notes.md").read_text()
    assert "supersedes: shop/kit/kit-fodder-corpus" in notes
    assert "See `console/kit`" in notes
    assert any(f.code == "mv-prose" and f.path.endswith("lab-sync-notes.md:10") for f in out)

    # the router entry moves to a new area section, ahead of anything that is not an area
    router = (fx.store / "ROUTER.md").read_text()
    assert "- console/kit" not in router
    assert router.index("## shop\n- shop/kit (") > router.index("- home/lab")
    assert {"mv-router-new-area", "mv-router-area-empty"} <= codes

    log = git(fx.store, "log", "--format=%s", "-2").splitlines()
    assert log[0] == "mv-territory: console/kit -> shop/kit"


def test_a_rename_in_place_keeps_the_router_line_where_it_was(store: Fixture):
    fx = store
    before = (fx.store / "ROUTER.md").read_text()
    out = moved(fx, "home/lab", "home/bench")
    after = (fx.store / "ROUTER.md").read_text()
    assert after == before.replace("- home/lab (2)", "- home/bench (3)")   # render recounts
    assert "consumes: home/bench" in (fx.store / "territories/console/kit/MEMORY.md").read_text()
    # GATES.md names it in prose: reported for a person to decide
    assert any(f.code == "mv-prose" and f.path.startswith("GATES.md") for f in out)
    assert (fx.store / "GATES.md").read_text().count("home/lab") == 1


def test_a_grouped_entry_is_renamed_in_place_and_flagged(store: Fixture):
    fx = store
    r = fx.store / "ROUTER.md"
    r.write_text(r.read_text().replace("- home/lab (2) :", "- home/lab, home/attic :"))
    mv = move.plan_territory(fx.store, fx.projects, "home/lab", "yard/lab")
    assert "- yard/lab, home/attic :" in mv.edits[r]
    assert "mv-router-grouped" in {f.code for f in mv.notes}


def test_an_approved_plan_follows_and_stays_approved(store: Fixture):
    fx = store
    plan = {"silos": [{"silo": "-Users-nobody-alpha", "territory": "console/kit", "mode": "active",
                       "files": [{"file": "a.md", "action": "relocate", "to": "home/lab"}]}]}
    P.write(fx.store, P.approve(plan))
    moved(fx, "console/kit", "shop/kit")
    got = P.load(fx.store)
    assert got["silos"][0]["territory"] == "shop/kit"
    assert got["approved"]["decisions"] == P.decisions(got)


def test_refusals_and_the_dry_run_write_nothing(store: Fixture):
    fx = store
    for old, new, code in (("home/none", "home/x", "mv-no-territory"),
                           ("home/lab", "console/kit", "mv-target-exists"),
                           ("home/lab", "Home/Lab", "mv-bad-name")):
        got = move.plan_territory(fx.store, fx.projects, old, new)
        assert isinstance(got, list) and got[0].code == code
    rc, out, _ = run(mem_cmd("mv-territory", "console/kit", "shop/kit",
                             "--root", str(fx.store), "--legacy", str(fx.projects)), fx.env())
    assert rc == 0 and "would move to territories/shop/kit" in out
    assert git(fx.store, "status", "--porcelain") == ""
    assert (fx.store / "territories/console/kit/MEMORY.md").is_file()


def test_an_error_the_move_creates_is_reported_with_the_way_back(store: Fixture):
    fx = store
    lab = fx.store / "territories/home/lab/MEMORY.md"
    lab.write_text(lab.read_text().replace("consumed_by: console/kit", "consumed_by: console/*"))
    git(fx.store, "commit", "-qam", "glob")
    new = [f for f in moved(fx, "console/kit", "shop/kit") if f.code == "mv-new-error"]
    assert len(new) == 1 and "territory-ref-unknown" in new[0].message
    assert "mem mv-territory shop/kit console/kit --write" in new[0].message


def test_mv_carries_the_index_line_and_the_container_refs(store: Fixture):
    fx = store
    kit = fx.store / "territories/console/kit"
    (kit / "kit-backup-followup.md").write_text(
        "---\nname: kit-backup-followup\nkind: territory\nsupersedes: home/lab/lab-backup-plan\n"
        "description: The backup plan, redone.\nstatus: SHIPPED\nlast_verified: 2026-10-01\n"
        "---\n\nWas `home/lab/lab-backup-plan`.\n")
    git(fx.store, "add", "-A")
    git(fx.store, "commit", "-qm", "followup")
    fm = move.plan_files(fx.store, ["lab-backup-plan"], "console/kit")
    out = move.apply_files(fx.store, fx.projects, fm)
    assert "mv-new-error" not in {f.code for f in out}, out

    lab = fx.store / "territories/home/lab"
    assert not (lab / "lab-backup-plan.md").exists() and (kit / "lab-backup-plan.md").is_file()
    assert "lab-backup-plan" not in (lab / "MEMORY.md").read_text()
    # the hand-written line travels as written, not regenerated from the description
    # ...and lands beside the index's other entries, not in a new section
    idx = (kit / "MEMORY.md").read_text()
    assert ("- [Gone file](kit-gone-file.md) — listed, but deleted.\n"
            "- [Backup plan](lab-backup-plan.md) — nightly, verified by hand.\n") in idx
    assert idx.count("## MEMORIES") == 1
    follow = (kit / "kit-backup-followup.md").read_text()
    assert "supersedes: console/kit/lab-backup-plan" in follow
    assert "Was `home/lab/lab-backup-plan`." in follow          # prose: reported only
    assert any(f.code == "mv-prose" and "kit-backup-followup" in f.path for f in out)
    assert git(fx.store, "log", "--format=%s", "-1").strip() == \
        "mv: lab-backup-plan -> console/kit"


def test_carried_lines_follow_the_last_entry_under_any_heading():
    text = "# t\n\n## Topic\n- [A](a.md) — a\n\n## Notes\nprose\n"
    assert apply.after_last_entry(text, ["- [B](b.md) — b"]) == \
        "# t\n\n## Topic\n- [A](a.md) — a\n- [B](b.md) — b\n\n## Notes\nprose\n"
    assert apply.after_last_entry("# t\n", ["- [B](b.md) — b"]) == \
        "# t\n\n## MEMORIES\n- [B](b.md) — b\n"
    # an empty section takes the lines rather than gaining a twin
    assert apply.after_last_entry("# t\n\n## MEMORIES\n\n## Notes\n", ["- [B](b.md) — b"]) == \
        "# t\n\n## MEMORIES\n- [B](b.md) — b\n\n## Notes\n"


def test_reindex_adds_unlisted_files_beside_topic_entries(tmp_path: Path):
    tdir = tmp_path / "territories/home/lab"
    tdir.mkdir(parents=True)
    (tdir / "MEMORY.md").write_text("# home/lab\n\n## Topic\n- [A](a.md) — a\n\n## Notes\nprose\n")
    (tdir / "a.md").write_text("---\nname: a\ndescription: a\n---\n")
    (tdir / "b.md").write_text("---\nname: b\ndescription: the b one\n---\n")
    apply.reindex(tmp_path, "home/lab")
    assert (tdir / "MEMORY.md").read_text() == \
        "# home/lab\n\n## Topic\n- [A](a.md) — a\n- [b](b.md) — the b one\n\n## Notes\nprose\n"


def test_mv_into_a_rendered_index_renders_it(store: Fixture):
    fx = store
    rc, _, err = run(mem_cmd("render", "console/kit", "--adopt", "--write"), fx.env())
    assert rc == 0, err
    git(fx.store, "commit", "-qam", "adopt")
    move.apply_files(fx.store, fx.projects,
                     move.plan_files(fx.store, ["home/lab/lab-backup-plan"], "console/kit"))
    text = (fx.store / "territories/console/kit/MEMORY.md").read_text()
    section = text[text.index("<!-- mem:render begin"):]
    assert "(lab-backup-plan.md)" in section and "(lab-backup-plan.md)" not in text[
        text.index("<!-- mem:render end"):]


def test_mv_refuses_and_warns(store: Fixture):
    fx = store
    (fx.store / "territories/console/kit/lab-twin.md").write_text("---\nname: lab-twin\n---\n")
    (fx.store / "territories/home/lab/lab-twin.md").write_text("---\nname: lab-twin\n---\n")
    for specs, dest, code in ((["lab-twin"], "home/lab", "mv-ambiguous"),
                              (["lab-backup-plan"], "home/lab", "mv-same-territory"),
                              (["home/lab/lab-twin"], "console/kit", "mv-target-exists"),
                              (["no-such-slug"], "console/kit", "mv-no-memory"),
                              (["home/lab/MEMORY"], "console/kit", "mv-not-memory"),
                              (["lab-backup-plan", "lab-backup-plan"], "console/kit",
                               "mv-duplicate"),
                              (["lab-backup-plan"], "home/none", "mv-no-territory")):
        got = move.plan_files(fx.store, specs, dest)
        assert isinstance(got, list) and code in {f.code for f in got}, (specs, got)
    fm = move.plan_files(fx.store, ["lab-ssh-read-only"], "console/kit")
    assert "mv-gate" in {f.code for f in fm.notes}
    rc, out, _ = run(mem_cmd("mv", "lab-backup-plan", "console/kit", "--root", str(fx.store),
                             "--legacy", str(fx.projects)), fx.env())
    assert rc == 0 and "would move to territories/console/kit/lab-backup-plan.md" in out
    assert (fx.store / "territories/home/lab/lab-backup-plan.md").is_file()


def archived(fx: Fixture, targets: list[str], why: str = "done with it", group=None) -> list:
    ar = move.plan_archive(fx.store, fx.projects, targets, why, group)
    assert isinstance(ar, move.Archive), ar
    return move.apply_archive(fx.store, fx.projects, ar)


def test_archiving_a_territory_retires_it_whole_and_unlinks_its_silos(store: Fixture):
    fx = store
    notes = fx.store / "territories/home/lab/lab-sync-notes.md"
    notes.write_text(notes.read_text() + "Design: [[kit-sync-design]].\n")
    git(fx.store, "commit", "-qam", "link")
    out = archived(fx, ["console/kit"], why="the kit was sold")
    assert "mv-new-error" not in {f.code for f in out}, out

    g = fx.store / "archive/console-kit"
    assert not (fx.store / "territories/console").exists()
    assert (g / "MEMORY.md").is_file() and (g / "kit-sync-design.md").is_file()
    assert "the kit was sold" in (g / "WHY-ARCHIVED.md").read_text()

    # the repo's silo no longer loads retired memory; relinking is a separate step
    assert not any(p.is_symlink() for p in fx.projects.glob("*/memory"))
    assert any(f.code == "archive-unlink" for f in out)

    router = (fx.store / "ROUTER.md").read_text()
    assert "console/kit" not in router and "mv-router-area-empty" in {f.code for f in out}
    lab = (fx.store / "territories/home/lab/MEMORY.md").read_text()
    assert "consumed_by: none" in lab
    text = notes.read_text()
    assert "supersedes: archive/console-kit/kit-fodder-corpus" in text
    assert "Design: `archive/console-kit/kit-sync-design.md`." in text
    assert git(fx.store, "log", "--format=%s", "-1").strip() == "archive: console/kit"


def test_a_merge_archives_the_emptied_territory(store: Fixture):
    # merging home/lab into console/kit: move every memory, then retire the bare index
    fx = store
    lab = fx.store / "territories/home/lab"
    slugs = [f"home/lab/{p.stem}" for p in sorted(lab.glob("*.md"))
             if p.name not in ("MEMORY.md", "EXPORTS.md")]
    move.apply_files(fx.store, fx.projects, move.plan_files(fx.store, slugs, "console/kit"))
    out = archived(fx, ["home/lab"], why="merged into console/kit")
    assert "mv-new-error" not in {f.code for f in out}, out
    assert (fx.store / "archive/home-lab/MEMORY.md").is_file()
    assert not lab.exists()


def test_archiving_memories_reindexes_and_logs_each_call(store: Fixture):
    fx = store
    design = fx.store / "territories/console/kit/kit-sync-design.md"
    design.write_text(design.read_text() + "Backups: [[lab-backup-plan]].\n")
    git(fx.store, "commit", "-qam", "link")
    archived(fx, ["lab-backup-plan"], why="replaced by snapshots")
    lab = fx.store / "territories/home/lab"
    assert not (lab / "lab-backup-plan.md").exists()
    assert "lab-backup-plan" not in (lab / "MEMORY.md").read_text()
    assert "`archive/home-lab/lab-backup-plan.md`" in design.read_text()
    assert any(p.is_symlink() for p in fx.projects.glob("*/memory"))   # silos untouched

    out = archived(fx, ["lab-sync-notes"], why="folded into the runbook")
    log = (fx.store / "archive/home-lab/WHY-ARCHIVED.md").read_text()
    assert log.count("# Archived") == 1 and "snapshots" in log and "runbook" in log
    # only the gate is left, and it is a memory too, so the territory is not empty yet
    assert "archive-territory-empty" not in {f.code for f in out}


def test_archive_refuses_and_warns(store: Fixture):
    fx = store
    (fx.store / "archive/home-lab").mkdir(parents=True)
    for targets, why, group, code in (
            (["home/lab"], "", None, "archive-no-why"),
            (["home/lab", "kit-sync-v1"], "x", None, "archive-mixed"),
            (["home/lab"], "x", None, "archive-group-exists"),
            (["lab-backup-plan", "kit-sync-v1"], "x", None, "archive-no-group"),
            (["kit-sync-v1", "kit-sync-v1"], "x", None, "mv-duplicate"),
            (["kit-sync-v1"], "x", "Bad Group", "mv-bad-name")):
        got = move.plan_archive(fx.store, fx.projects, targets, why, group)
        assert isinstance(got, list) and code in {f.code for f in got}, (targets, got)
    ar = move.plan_archive(fx.store, fx.projects, ["lab-ssh-read-only"], "x", "lab-gates")
    assert "mv-gate" in {f.code for f in ar.notes}
    rc, out, _ = run(mem_cmd("archive", "console/kit", "--why", "x", "--root", str(fx.store),
                             "--legacy", str(fx.projects)), fx.env())
    assert rc == 0 and "would archive to archive/console-kit" in out
    assert (fx.store / "territories/console/kit/MEMORY.md").is_file()
