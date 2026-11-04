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
    # the harness block is flattened in the same pass, so `note` lands at the top level
    assert meta["description"] == desc and meta["note"] == "a: b" and "metadata" not in meta


def test_fix_leaves_frontmatter_it_cannot_verify(fx: Fixture):
    p = fx.store / "territories/console/kit/kit-keyless.md"
    raw = "---\nname: kit-keyless\nkind: territory\ndescription: d: e\n[not a key\n---\nB.\n"
    p.write_text(raw)
    mems, routers = scan_store(fx.store)
    f = do_fix(mems, routers, write=True, stamp_today=False)
    assert any(x.code == "fix-frontmatter-skip" and x.path == str(p) for x in f)
    assert p.read_text() == raw


def test_fix_strips_retired_recipe_fields_and_nothing_else(fx: Fixture):
    p = fx.store / "territories/console/kit/kit-recipe.md"
    p.write_text("---\nname: kit-recipe\nkind: territory\ndescription: d\nvolatility: slow\n"
                 "verify: gh pr view 1 --json state -q .state\nexpect: MERGED\n"
                 "unrunnable: true\nlast_verified: 2026-10-01\n---\n\n"
                 "Body keeps verify: and expect: as prose.\n")
    mems, routers = scan_store(fx.store)
    f = do_fix(mems, routers, write=True, stamp_today=False)
    assert any(x.path == str(p) and "obsolete-field" in x.message for x in f)
    assert p.read_text() == (
        "---\nname: kit-recipe\nkind: territory\ndescription: d\nvolatility: slow\n"
        "last_verified: 2026-10-01\n---\n\nBody keeps verify: and expect: as prose.\n")


def test_fix_strips_retired_fields_nested_under_harness_metadata(fx: Fixture):
    """The harness's auto-memory writes keys under `metadata:`; the loader hoists them, so
    the audit flags them, and fix must reach them too (two real files on 2026-11-04)."""
    p = fx.store / "territories/console/kit/kit-nested.md"
    p.write_text("---\nname: kit-nested\ndescription: d\nmetadata:\n  kind: territory\n"
                 '  verify: "git -C /x grep -n \\"uv run\\" -- Makefile"\n  expect: uv run\n'
                 "  last_verified: 2026-10-27\nvolatility: slow\n---\n\nB.\n")
    mems, routers = scan_store(fx.store)
    do_fix(mems, routers, write=True, stamp_today=False)
    assert p.read_text() == ("---\nname: kit-nested\ndescription: d\n"
                             "kind: territory\nlast_verified: 2026-10-27\n"
                             "volatility: slow\n---\n\nB.\n")


def test_fix_flattens_the_harness_metadata_block(fx: Fixture):
    """Synthetic, in the shape of the 228 real files of 2026-11-04: the harness's own keys
    go, everything else moves up a level, a top-level key wins over its nested copy, and
    `modified` survives only where there is no last_verified to stand in for it."""
    from claude_hybrid_memory.fix import flatten_harness
    text = ("---\nname: kit-h\ndescription: d\nmetadata:\n  node_type: memory\n"
            "  kind: territory\n  type: project\n  originSessionId: 0000\n"
            "  modified: 2026-08-13T23:58:04.986Z\n  description: older\n"
            "last_verified: 2026-09-11\nvolatility: slow\n---\n\nBody.\n")
    new, actions = flatten_harness(text)
    assert new == ("---\nname: kit-h\ndescription: d\nkind: territory\n"
                   "last_verified: 2026-09-11\nvolatility: slow\n---\n\nBody.\n")
    assert "dropped description (already at top level)" in actions
    no_lv = text.replace("last_verified: 2026-09-11\n", "")
    assert "modified: 2026-08-13T23:58:04.986Z\n" in flatten_harness(no_lv)[0]
    # a router: nested maps dedent, the empty harness name goes, modified never stays
    router = ("---\nname: \"\"\nmetadata:\n  node_type: memory\n  territory: solo/x\n"
              "  members:\n    x:\n      mode: active\n  modified: 2026-10-24T12:59:07Z\n"
              "---\n\n# solo/x\n")
    new, _ = flatten_harness(router, router=True)
    assert new == ("---\nterritory: solo/x\nmembers:\n  x:\n    mode: active\n---\n\n"
                   "# solo/x\n")
    assert flatten_harness("---\nname: a\nkind: territory\n---\nB.\n") is None


def test_audit_warns_on_a_harness_written_memory(fx: Fixture):
    from claude_hybrid_memory.audit.structure import check_structure
    mems, _ = scan_store(fx.store)
    f = [x for x in check_structure(mems) if x.code == "harness-frontmatter"]
    assert [x.path.rsplit("/", 1)[1] for x in f] == ["lab-backup-plan.md"]


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
    assert [x.code for x in f] == ["link-done", "link-members"]
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
    assert [x.code for x in f] == ["link-done", "link-members"]
    assert (silo / "memory" / "MEMORY.md").is_file()


def test_link_records_the_repo_in_members_and_keeps_the_rest(fx: Fixture, tmp_path: Path):
    # Synthetic. `link --write` was the one writer of the repo-territory relationship and
    # never recorded it, so `members:` drifted from the silos (eval 2026-11-04).
    from claude_hybrid_memory.silos import has_member, with_member
    idx = fx.store / "territories/home/lab/MEMORY.md"
    before = idx.read_text()
    assert do_link(fx.store, fx.projects, "home/lab", fx.elsewhere, write=False)[0].message \
        .endswith(f"and add `{fx.elsewhere.name}` to its members: (rerun with --write)")
    assert idx.read_text() == before                     # a dry run writes nothing
    do_link(fx.store, fx.projects, "home/lab", fx.elsewhere, write=True)
    after = idx.read_text()
    assert has_member(after, fx.elsewhere.name)
    assert f"  {fx.elsewhere.name}: {{owner: self, mode: active}}\n" in after
    assert after.replace(f"members:\n  {fx.elsewhere.name}: {{owner: self, mode: active}}\n",
                         "") == before                  # nothing else in the file moved
    # an existing block keeps its entries, flow style and comments
    text = ("---\nterritory: x\nmembers:\n  a: {owner: self, mode: dead}  # parked\n"
            "consumes: none\n---\n# x\n")
    out = with_member(text, "b")
    assert out == ("---\nterritory: x\nmembers:\n  a: {owner: self, mode: dead}  # parked\n"
                   "  b: {owner: self, mode: active}\nconsumes: none\n---\n# x\n")
    assert has_member(out, "a") and has_member(out, "b") and not has_member(out, "c")
