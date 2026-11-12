from __future__ import annotations

import datetime as dt
from pathlib import Path

from conftest import Fixture

from claude_hybrid_memory import audit
from claude_hybrid_memory.store import scan_legacy, scan_store

TODAY = dt.date(2026, 10, 21)


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level == level}


def scanned(fx: Fixture):
    mems, routers = scan_store(fx.store)
    lm, lr = scan_legacy(fx.projects)
    return mems + lm, {**routers, **lr}


def test_structure_flags_the_broken_file(fx: Fixture):
    mems, _ = scanned(fx)
    found = {(f.code, f.path.rsplit("/", 1)[-1]) for f in audit.check_structure(mems)}
    assert ("missing-name", "kit_raw_notes.md") in found
    assert ("bad-slug", "kit_raw_notes.md") in found
    # a value outside a field's vocabulary is a refine item, not an error (spec.REFINE_CODES)
    bad = [
        f
        for f in audit.check_structure(mems)
        if f.code == "field-invalid" and f.path.endswith("kit-bad-recipe.md")
    ]
    assert {f.message.split()[0] for f in bad} >= {"status", "last_verified"}
    assert all(f.level == "info" for f in bad)


def test_links(fx: Fixture):
    mems, routers = scanned(fx)
    f = audit.check_links(mems, routers)
    assert "dangling-link" in codes(f, "error")  # [[kit-missing-note]]
    assert "ambiguous-slug" in codes(f, "error")  # kit-sync-v1 in store AND a silo
    assert "orphan" in codes(f, "warn")
    not_links = {x.path for x in f if x.code == "not-a-wikilink"}
    assert {"var", "override"} <= not_links


def test_router_drift(fx: Fixture):
    mems, routers = scanned(fx)
    f = audit.check_router_drift(mems, routers)
    ghosts = [x.message for x in f if x.code == "router-ghost"]
    assert ghosts == ["lists kit-gone-file.md which does not exist"]


def test_exports_must_be_inlined_in_the_consumer(fx: Fixture):
    _, routers = scanned(fx)
    f = audit.check_exports(fx.store, routers)
    missing = [x for x in f if x.code == "export-not-inlined"]
    assert len(missing) == 1 and "parks disks" in missing[0].message


def test_a_superseded_file_is_not_at_fault_but_its_index_line_is(fx: Fixture):
    # kit-sync-v1 stays SHIPPED and byte-identical by design (direction §6); the router still
    # listing it is what sends a session to the old word.
    _, routers = scanned(fx)
    f = audit.check_chains(fx.store, routers)
    assert [(x.code, x.path.rsplit("/", 2)[-2:]) for x in f] == [
        ("superseded-still-indexed", ["kit", "MEMORY.md"])
    ]
    assert "kit-sync-v1.md" in f[0].message and "console/kit/kit-sync-design" in f[0].message


def test_freshness(fx: Fixture):
    mems, _ = scanned(fx)
    f = audit.check_freshness(mems, TODAY)
    assert "stale-live" in codes(f, "warn")
    assert not codes(f) & {"verify-refused", "verify-due"}  # recipes are no longer run


def test_a_record_is_never_stale_and_needs_no_volatility(fx: Fixture):
    """format-spec: a `tier: record` is dated history with no "last seen true". The
    2026-11-04 retro found all 52 of a real store's records reported twice, as `stale` and as
    `no-volatility`: 104 findings with nothing to do about any of them."""
    rec = fx.store / "territories/console/kit/kit-bench-run-2025-01.md"
    rec.write_text(
        "---\nname: kit-bench-run-2025-01\nkind: territory\ntier: record\n"
        "description: The January 2025 bench run.\n---\n\nNumbers.\n"
    )
    mems, _ = scanned(fx)
    hit = lambda f: [x.code for x in f if x.path == str(rec)]  # noqa: E731
    assert hit(audit.check_freshness(mems, TODAY)) == []
    assert hit(audit.check_structure(mems)) == []


def test_retired_recipe_fields_are_flagged(fx: Fixture):
    mems, _ = scanned(fx)
    old = {
        f.path.rsplit("/", 1)[-1]: f
        for f in audit.check_structure(mems)
        if f.code == "obsolete-field"
    }
    assert set(old) >= {"kit-fodder-corpus.md", "kit-bad-recipe.md"}
    assert old["kit-bad-recipe.md"].level == "info"


def test_budget_cliff(fx: Fixture, fx_oversized: Fixture):
    mems, _ = scanned(fx)
    assert "budget-truncating" not in codes(audit.check_budget(fx.store, mems))
    mems, _ = scanned(fx_oversized)
    assert "budget-truncating" in codes(audit.check_budget(fx_oversized.store, mems), "error")


def test_silos(fx: Fixture):
    f = audit.check_silos(fx.projects, fx.store)
    by = {x.code: x for x in f}
    assert "silo-migrated" in by
    assert "silo-mixed-state" in by and "kit-sync-v1" in by["silo-mixed-state"].message
    assert "silo-not-checked-out" in by  # /Users/nobody does not exist on this disk


def test_dup_hint_crosses_containers_only(fx: Fixture):
    mems, _ = scanned(fx)
    f = audit.check_dup(mems)
    assert all(x.level == "info" for x in f)


def test_secret_scan_never_prints_the_value(fx: Fixture):
    key = "AKIA" + "QZ7X" * 4  # built here so no key-shaped literal sits in the repo
    p = fx.store / "territories/home/lab/lab-backup-plan.md"
    p.write_text(p.read_text() + f"\naws_access_key_id = {key}\n")
    f = audit.check_secrets(fx.store, [])
    hits = [x for x in f if x.code == "secret"]
    assert len(hits) == 1 and hits[0].level == "error" and "aws-access-key" in hits[0].message
    assert key not in " ".join(x.message for x in f)


def test_secret_scan_ignores_code_that_names_a_secret(fx: Fixture):
    # switch-nax0-crypto.md's shape: Python slicing assigned to a variable named `secret`
    p = fx.store / "territories/console/kit/kit-sync-design.md"
    p.write_text(
        p.read_text() + "\n    secret = kek_src[:0x10],\n    token = derive_token_for_session\n"
    )
    assert audit.check_secrets(fx.store, []) == []
    p.write_text(p.read_text() + "\napi_key: 9f8e7d6c5b4a39281706f5e4\n")
    assert codes(audit.check_secrets(fx.store, []), "warn") == {"secret-maybe"}


def test_split_candidates_rank_by_size_markers_and_reads(fx: Fixture):
    from collections import Counter

    t = fx.store / "territories/console/kit"
    (t / "kit-big-log.md").write_text(
        "---\nname: kit-big-log\nkind: territory\ndescription: big, accreted\n---\n\n"
        "Read bottom-up.\n\n## CORRECTION\n\n" + "x " * 6000 + "\n"
    )
    (t / "kit-big-plain.md").write_text(
        "---\nname: kit-big-plain\nkind: territory\ndescription: big, plain\n---\n\n" + "y " * 7000
    )
    mems, _ = scanned(fx)
    f = [x for x in audit.check_split(mems, Counter(), fx.store) if x.code == "split-candidate"]
    assert [x.path.split("/")[-1] for x in f] == ["kit-big-log.md", "kit-big-plain.md"]
    # reads reorder it: the plain file is the one sessions actually pay for
    reads = Counter({"territories/console/kit/kit-big-plain.md": 5})
    f = [x for x in audit.check_split(mems, reads, fx.store) if x.code == "split-candidate"]
    assert f[0].path.endswith("kit-big-plain.md") and "read 5x" in f[0].message
    acc = [x for x in audit.check_split(mems, Counter(), fx.store) if x.code == "accretion"]
    assert acc and acc[0].message.startswith("1 of ")


def test_budget_checks_delivery_not_just_tokens(fx: Fixture, tmp_path: Path, monkeypatch):
    from claude_hybrid_memory.hooks import session_start

    md = tmp_path / "CLAUDE.md"
    md.write_text("# Git\n")
    f = audit.budget.check_delivery(fx.store, md)
    assert {"budget-not-imported", "budget-always-stale"} <= codes(f)
    md.write_text(f"{session_start.import_line(fx.store)}\n")
    session_start.write_always(fx.store)
    assert audit.budget.check_delivery(fx.store, md) == []
    monkeypatch.setattr(session_start, "HOOK_OUTPUT_LIMIT", 50)
    assert "budget-hook-output" in codes(audit.budget.check_delivery(fx.store, md), "error")
    monkeypatch.undo()
    # the rules file is the import now; CLAUDE.md importing as well loads the layer twice
    rules = session_start.rules_path(md)
    rules.parent.mkdir()
    rules.write_text(session_start.rules_text(fx.store))
    assert codes(audit.budget.check_delivery(fx.store, md)) == {"budget-imported-twice"}
    md.write_text("# Git\n")
    assert audit.budget.check_delivery(fx.store, md) == []


def test_a_silo_whose_territory_was_renamed_is_an_error(fx: Fixture):
    # A territory renamed by hand, its silo not repointed: exists() follows the dead link,
    # so the audit used to say nothing.
    silo = fx.projects / "-Users-nobody-renamed-repo"
    silo.mkdir()
    (silo / "memory").symlink_to(fx.store / "territories" / "home" / "gone")
    by = {x.code: x for x in audit.check_silos(fx.projects, fx.store)}
    assert by["silo-dangling"].level == "error" and by["silo-dangling"].path == silo.name


def test_a_superseded_memory_is_never_stale(fx: Fixture):
    """It is never edited by design, so a staleness finding on it could never clear."""
    v1 = fx.store / "territories/console/kit/kit-sync-v1.md"
    v1.write_text(v1.read_text().replace("status: SHIPPED\n", "volatility: live\n"))
    mems, _ = scanned(fx)
    hit = lambda f: [x for x in f if x.path == str(v1)]  # noqa: E731 - the store copy only
    assert hit(audit.check_freshness(mems, TODAY))
    assert not hit(audit.check_freshness(mems, TODAY, audit.superseded_paths(fx.store)))


def test_upkeep_checks_skip_what_is_not_live(fx: Fixture):
    """One predicate (`is_live`) for every upkeep check: a superseded original or a
    `tier: record` gets no `no-volatility`, `stale` or `split-candidate`, since none of
    them could ever be cleared (retro 2026-11-12: six `no-volatility` on superseded files)."""
    from collections import Counter

    v1 = fx.store / "territories/console/kit/kit-sync-v1.md"
    v1.write_text(v1.read_text().replace("status: SHIPPED\n", "") + "z " * 6000)
    rec = fx.store / "territories/console/kit/kit-2026-10-incident.md"
    rec.write_text(
        "---\nname: kit-2026-10-incident\nkind: territory\ndescription: dated\n"
        "tier: record\n---\n\n" + "r " * 6000
    )
    mems, _ = scanned(fx)
    sup = audit.superseded_paths(fx.store)
    paths = {str(v1), str(rec)}
    hit = lambda f: {x.code for x in f if x.path in paths}  # noqa: E731
    assert {"no-volatility", "split-candidate"} <= hit(
        audit.check_structure(mems) + audit.check_split(mems, Counter(), fx.store)
    )
    assert not hit(
        audit.check_structure(mems, sup)
        + audit.check_split(mems, Counter(), fx.store, sup)
        + audit.check_freshness(mems, TODAY, sup)
    )


def _big(t: Path, slug: str, kb: float, extra: str = "") -> Path:
    p = t / f"{slug}.md"
    head = f"---\nname: {slug}\nkind: territory\ndescription: big\n{extra}---\n\n"
    p.write_text(head + "y" * int(kb * 1024))
    return p


def test_splittable_no_holds_until_its_ceiling(fx: Fixture):
    """A declined split stays quiet under the ceiling `mem no-split` wrote, is counted on
    one INFO line, and comes back with Matt's reason once the file grows past it. The
    real case: 7-8 of ~300 work-Mac files re-raised by every retro after being declined."""
    from collections import Counter

    from claude_hybrid_memory.audit.split import ceiling_for, field_value, no_split

    assert (ceiling_for(15 * 1024), ceiling_for(21 * 1024), ceiling_for(20 * 1024)) == (20, 30, 30)
    assert no_split({"splittable": False}) == (None, "")  # YAML's reading of a bare `no`
    assert no_split({"splittable": "yes, by topic"}) is None
    assert no_split({"splittable": field_value(15 * 1024, "one argument")}) == (20, "one argument")

    t = fx.store / "territories/console/kit"
    held = _big(t, "kit-held", 15, 'splittable: "no until 20 KB: one argument"\n')
    over = _big(t, "kit-over", 22, 'splittable: "no until 20 KB: one argument"\n')
    bare = _big(t, "kit-bare", 12, "splittable: no\n")
    mems, _ = scanned(fx)
    f = audit.check_split(mems, Counter(), fx.store)
    by = {x.path: x for x in f if x.code == "split-candidate"}
    assert str(held) not in by
    assert "past the 20 KB ceiling" in by[str(over)].message
    assert "'one argument'" in by[str(over)].message
    assert "no ceiling" in by[str(bare)].message
    info = [x for x in f if x.code == "split-declined"]
    assert info and info[0].level == "info" and info[0].message.startswith("1 file(s)")


def test_a_retro_split_decline_asks_to_move_onto_the_file(fx: Fixture):
    """A `refine:split-candidate:` key in RETRO.md is reported with the exact command that
    migrates it, then goes quiet once the file carries `splittable:`."""
    from collections import Counter

    t = fx.store / "territories/console/kit"
    p = _big(t, "kit-declined", 14)
    rel = "territories/console/kit/kit-declined.md"
    (fx.store / "RETRO.md").write_text(
        f"# RETRO\n\n- `refine:split-candidate:{rel}` — one argument (Matt, 2026-11-04)\n"
    )
    mems, _ = scanned(fx)
    f = [x for x in audit.check_split(mems, Counter(), fx.store) if x.path == str(p)]
    assert [x.code for x in f] == ["split-decline-legacy"]
    assert f"mem no-split {rel} -m 'one argument (Matt, 2026-11-04)'" in f[0].message
    _big(t, "kit-declined", 14, 'splittable: "no until 20 KB: one argument"\n')
    mems, _ = scanned(fx)
    assert not [x for x in audit.check_split(mems, Counter(), fx.store) if x.path == str(p)]
