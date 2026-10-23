from __future__ import annotations

from pathlib import Path

import pytest
from conftest import Fixture

from claude_hybrid_memory.fix import desired_slug, do_fix
from claude_hybrid_memory.harness import silo_name
from claude_hybrid_memory.silos import do_link, silo_workdir
from claude_hybrid_memory.store import parse_frontmatter, scan_store


@pytest.mark.parametrize("stem,want", [
    ("kit_raw_notes", "kit-raw-notes"),
    ("Feedback Approach", "feedback-approach"),
    ("already-fine", "already-fine"),
    ("a--b__c", "a-b-c"),
])
def test_desired_slug(stem: str, want: str):
    assert desired_slug(stem) == want


def test_fix_plans_rename_and_rewrites_links(fx: Fixture):
    (fx.store / "territories/console/kit/kit-sync-v1.md").write_text(
        "---\nname: kit-sync-v1\nkind: territory\ndescription: d.\nstatus: HISTORICAL\n---\n"
        "See [[kit_raw_notes]].\n")
    mems, routers = scan_store(fx.store)
    f = do_fix(mems, routers, write=True, stamp_today=False)
    raw = [x for x in f if x.path.endswith("kit_raw_notes.md")][0]
    assert "insert name: kit-raw-notes" in raw.message
    assert "rename -> kit-raw-notes.md" in raw.message
    assert "status: SHIPPED (lifted from description)" in raw.message
    kit = fx.store / "territories/console/kit"
    assert (kit / "kit-raw-notes.md").exists() and not (kit / "kit_raw_notes.md").exists()
    assert "[[kit-raw-notes]]" in (kit / "kit-sync-v1.md").read_text()


def test_fix_quotes_frontmatter_yaml_misreads(fx: Fixture):
    p = fx.store / "territories/console/kit/kit-colon.md"
    desc = "SHIPPED 2026-10-07 (PR #735): it's \"done\" now"
    p.write_text(f"---\nname: kit-colon\nkind: territory\ndescription: {desc}\n"
                 "status: SHIPPED\nmetadata:\n  note: a: b\n---\nBody.\n")
    mems, routers = scan_store(fx.store)
    assert [m for m in mems if m.path == p][0].fm_problems
    f = do_fix(mems, routers, write=True, stamp_today=False)
    assert "quoted description, note (frontmatter-not-yaml)" in \
        [x for x in f if x.path == str(p)][0].message
    meta, body, problems = parse_frontmatter(p.read_text())
    assert not problems and body == "Body.\n"
    assert meta["description"] == desc and meta["metadata"]["note"] == "a: b"


def test_fix_leaves_frontmatter_it_cannot_verify(fx: Fixture):
    p = fx.store / "territories/console/kit/kit-keyless.md"
    raw = "---\nname: kit-keyless\nkind: territory\ndescription: d: e\n[not a key\n---\nB.\n"
    p.write_text(raw)
    mems, routers = scan_store(fx.store)
    f = do_fix(mems, routers, write=True, stamp_today=False)
    assert any(x.code == "fix-frontmatter-skip" and x.path == str(p) for x in f)
    assert p.read_text() == raw


def test_fix_dry_run_writes_nothing(fx: Fixture):
    before = {p: p.read_text() for p in fx.store.rglob("*.md")}
    mems, routers = scan_store(fx.store)
    f = do_fix(mems, routers, write=False, stamp_today=False)
    assert any(x.code == "fix-dry-run" for x in f)
    assert {p: p.read_text() for p in fx.store.rglob("*.md")} == before


def test_link_refuses_an_occupied_silo(fx: Fixture, tmp_path: Path):
    target = (tmp_path / "occupied").resolve()
    target.mkdir()
    silo = fx.projects / silo_name(str(target))
    (silo / "memory").mkdir(parents=True)
    (silo / "memory" / "real-note.md").write_text("---\nname: real-note\n---\n")
    f = do_link(fx.store, fx.projects, "console/kit", target, write=True)
    assert [x.code for x in f] == ["link-silo-occupied"]
    assert not (silo / "memory").is_symlink()


def test_link_writes_and_is_idempotent(fx: Fixture):
    f = do_link(fx.store, fx.projects, "home/lab", fx.elsewhere, write=True)
    assert [x.code for x in f] == ["link-done"]
    again = do_link(fx.store, fx.projects, "home/lab", fx.elsewhere, write=True)
    assert [x.code for x in again] == ["link-already"]


def test_silo_workdir_round_trips_a_real_directory(tmp_path: Path):
    d = (tmp_path / "some.repo" / "with-dash").resolve()
    d.mkdir(parents=True)
    assert silo_workdir(silo_name(str(d))) == d
    assert silo_workdir("-Users-nobody-at-all") is None



def test_silo_workdir_reads_old_underscore_silos_and_odd_names(tmp_path: Path):
    d = (tmp_path / "Old_Vault" / ".config" / "My  Drive").resolve()
    d.mkdir(parents=True)
    assert silo_workdir(silo_name(str(d))) == d
    old = silo_name(str(d.parent.parent)).replace("Old-Vault", "Old_Vault")
    assert "Old_Vault" in old and silo_workdir(old) == d.parent.parent


def test_link_names_the_silo_the_harness_reads(fx: Fixture, tmp_path: Path):
    d = (tmp_path / "console_tools").resolve()
    d.mkdir()
    do_link(fx.store, fx.projects, "home/lab", d, write=True)
    assert (fx.projects / silo_name(str(d)) / "memory").is_symlink()
    assert "console-tools" in silo_name(str(d))


def test_link_repoints_a_silo_whose_territory_is_gone(fx: Fixture):
    silo = fx.projects / silo_name(str(fx.elsewhere))
    silo.mkdir(parents=True, exist_ok=True)
    (silo / "memory").symlink_to(fx.store / "territories" / "home" / "gone")
    f = do_link(fx.store, fx.projects, "home/lab", fx.elsewhere, write=True)
    assert [x.code for x in f] == ["link-done"]
    assert (silo / "memory" / "MEMORY.md").is_file()
