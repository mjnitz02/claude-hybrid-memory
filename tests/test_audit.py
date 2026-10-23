from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from conftest import Fixture

from claude_hybrid_memory import audit
from claude_hybrid_memory.audit.freshness import validate_recipe
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
    assert ("bad-status", "kit-bad-recipe.md") in found
    assert ("bad-date", "kit-bad-recipe.md") in found


def test_links(fx: Fixture):
    mems, routers = scanned(fx)
    f = audit.check_links(mems, routers)
    assert "dangling-link" in codes(f, "error")      # [[kit-missing-note]]
    assert "ambiguous-slug" in codes(f, "error")     # kit-sync-v1 in store AND a silo
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
    assert [(x.code, x.path.rsplit("/", 2)[-2:]) for x in f] == \
        [("superseded-still-indexed", ["kit", "MEMORY.md"])]
    assert "kit-sync-v1.md" in f[0].message and "console/kit/kit-sync-design" in f[0].message


def test_freshness(fx: Fixture):
    mems, _ = scanned(fx)
    f = audit.check_freshness(mems, TODAY, run=False)
    assert "verify-refused" in codes(f, "error")
    assert "verify-due" in codes(f)
    assert "stale-live" in codes(f, "warn")


@pytest.mark.parametrize("cmd,ok", [
    ("gh pr view 1 --json state -q .state", True),
    ("test -d /tmp", True),
    ("git log | head", False),
    ("curl https://example.com", False),
    ("git push origin main", False),
    ("gh pr merge 4", False),
    ("git log $(whoami)", False),
    ("", False),
])
def test_validate_recipe(cmd: str, ok: bool):
    argv, err = validate_recipe(cmd)
    assert (argv is not None) is ok and (err is None) is ok


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
    assert "silo-not-checked-out" in by   # /Users/nobody does not exist on this disk


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
    p.write_text(p.read_text()
                 + "\n    secret = kek_src[:0x10],\n    token = derive_token_for_session\n")
    assert audit.check_secrets(fx.store, []) == []
    p.write_text(p.read_text() + "\napi_key: 9f8e7d6c5b4a39281706f5e4\n")
    assert codes(audit.check_secrets(fx.store, []), "warn") == {"secret-maybe"}


def test_split_candidates_rank_by_size_markers_and_reads(fx: Fixture):
    from collections import Counter
    t = fx.store / "territories/console/kit"
    (t / "kit-big-log.md").write_text(
        "---\nname: kit-big-log\nkind: territory\ndescription: big, accreted\n---\n\n"
        "Read bottom-up.\n\n## CORRECTION\n\n" + "x " * 6000 + "\n")
    (t / "kit-big-plain.md").write_text(
        "---\nname: kit-big-plain\nkind: territory\ndescription: big, plain\n---\n\n" + "y " * 7000)
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
