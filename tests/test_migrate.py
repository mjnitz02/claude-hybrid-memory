"""Fast adoption (fast-adoption §4-8): inventory, the summarizer (faked), map, apply, queue.

No test here calls a model. The fake summarizer answers in `claude -p --output-format json`
shape, from the schema it is handed, and logs its argv so the isolation flags are checked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import Fixture, mem_cmd, run

from claude_hybrid_memory.migrate import apply, inventory, summarize

FAKE = r'''
import json, os, sys
args = sys.argv[1:]
schema = json.loads(args[args.index("--json-schema") + 1])
data = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": args, "cwd": os.getcwd(), "ls": os.listdir(".")}) + "\n")
if "FAIL-ALWAYS" in data:
    print("not json"); sys.exit(1)
once = os.path.join(os.environ["FAKE_STATE"], "failed-once")
if "FAIL-ONCE" in data and not os.path.exists(once):
    open(once, "w").close(); print("not json"); sys.exit(1)
if "SCHEMA-BREAK" in data:
    out = {"conclusion": 3}
elif "subject" in schema["properties"]:
    # beta claims an existing territory, and mislabels it "new", as the real run did once
    beta = "project: beta-repo" in data
    out = {"subject": "a fixture", "summary": "Fixture memories.", "territory_existing": None,
           "territory_new": "home/lab" if beta else "fixture/alpha", "why": "nothing fits",
           "mode": "active", "confidence": "high"}
else:
    name = data.split("file: ", 1)[1].split("\n", 1)[0]
    out = {"conclusion": "Conclusion of " + name, "description_verdict": "names-subject",
           "kind": "territory", "subject_repos": [], "territory_hint": None,
           "shape": ["dated-snapshot"], "verify": [], "obsolete": {"likely": False, "why": ""},
           "confidence": "high"}
    if "OBSOLETE-MARK" in data:
        out["obsolete"] = {"likely": True, "why": "retired"}
    if "HINT-LAB" in data:
        out["territory_hint"] = "home/lab"
    if "HINT-NOWHERE" in data:
        out["territory_hint"] = "the resume"
    if "GOOD-DESC" in data:
        out["description_verdict"] = "good"
    if "STANDING-MARK" in data:
        out["kind"] = "standing-candidate"
    if "VERIFY-MARK" in data:
        out["verify"] = [{"claim": "the fix is uncommitted", "why": "it may have landed",
                          "identifier": "abc1234"}]
    if "LOW-CONF" in data:
        out["confidence"] = "low"
print(json.dumps({"type": "result", "is_error": False, "structured_output": out,
                  "usage": {"input_tokens": 100, "cache_creation_input_tokens": 20,
                            "output_tokens": 7},
                  "total_cost_usd": 0.01, "modelUsage": {"claude-sonnet-fixture": {}}}))
'''

ALPHA = "-Users-nobody-workspaces-alpha"
BETA = "-Users-nobody-workspaces-beta-repo"


def silo(fx: Fixture, name: str, files: dict[str, str]) -> Path:
    md = fx.projects / name / "memory"
    md.mkdir(parents=True)
    for f, text in files.items():
        (md / f).write_text(text, encoding="utf-8")
    return md


@pytest.fixture
def silos(fx: Fixture) -> Fixture:
    silo(fx, ALPHA, {
        "MEMORY.md": "# Memory Index\n\n- [Deploy notes](deploy-notes.md) — how alpha ships\n",
        "deploy-notes.md": (
            "---\nname: deploy-notes\ndescription: Alpha deploys through the nightly bench "
            "pipeline with signed artifacts\n---\n\n"
            "Fixed in commit `abc1234`, see PR #12. Shares a schema with beta-repo.\n"
            "As of 2026-09-01 the fix is uncommitted.\n"
            "Mockup at https://claude.ai/code/artifact/ca7d5214-dd16-4f6f-a4f0-bdce31a0e3eb\n"
            "Mail ci-bot-385983851@site-alpha.iam.example.com about it.\n"
            "Home is /Users/alpha/workspaces, ignore it.\n"),
        "launch-record.md": (
            "---\nname: launch-record\ntier: record\ndescription: The 1.0 launch\n---\n\n"
            "Shipped at commit `def5678`.\n"),
    })
    silo(fx, BETA, {"schema-notes.md": (
        "---\nname: schema-notes\ndescription: Beta deploys through the nightly bench "
        "pipeline with signed artifacts too\n---\n\nSame pipeline.\n")})
    # a migrated silo: its dir is a symlink, so it is never pending
    (fx.projects / "-Users-nobody-done" ).mkdir()
    (fx.projects / "-Users-nobody-done" / "memory").symlink_to(
        fx.store / "territories" / "home" / "lab")
    return fx


def files_by_name(inv: dict) -> dict[str, dict]:
    return {f["file"]: f for f in inv["files"]}


def test_pending_silos_skip_empty_and_migrated(silos: Fixture):
    names = [p.parent.name for p in inventory.pending_silos(silos.projects)]
    assert ALPHA in names and BETA in names and "-Users-nobody-gone-repo" in names
    assert "-Users-nobody-done" not in names and "-Users-nobody-empty" not in names


def test_inventory_signals(silos: Fixture):
    inv = inventory.build(silos.store, inventory.pending_silos(silos.projects))
    f = files_by_name(inv)
    d = f["deploy-notes.md"]
    assert d["index_line"].startswith("- [Deploy notes](deploy-notes.md)")
    assert d["repos"] == ["beta-repo"]          # not its own repo, not the home path
    kinds = {c["kind"]: c["match"] for c in d["live_claims"]}
    assert kinds["sha"] == "abc1234" and "pr-or-issue" in kinds
    assert "uncommitted" in kinds and "as-of" in kinds
    assert not any("ca7d5214" in c["match"] or "385983851" in c["match"]
                   for c in d["live_claims"])
    assert f["launch-record.md"]["live_claims"] == []          # tier: record is exempt
    assert d["duplicates"][0]["id"] == f"{BETA}/schema-notes.md"
    assert len(d["sha256"]) == 64 and d["bytes"] > 0
    gone = next(s for s in inv["silos"] if s["silo"] == "-Users-nobody-gone-repo")
    assert gone["mixed_state"] == ["kit-sync-v1"] and gone["workdir"] is None


def test_live_claims_one_per_kind_and_line():
    hits = inventory.live_claims("commit `abc1234` and `abc1235` here\nPR #9\n")
    assert [h["kind"] for h in hits] == ["sha", "pr-or-issue"]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch) -> Path:
    bin_ = tmp_path / "fake-claude"
    bin_.write_text(f"#!{sys.executable}\n" + FAKE)
    bin_.chmod(0o755)
    log = tmp_path / "fake.log"
    monkeypatch.setenv(summarize.RUNNER_ENV, str(bin_))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_STATE", str(tmp_path))
    return log


def calls(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def jobs(fx: Fixture) -> list[summarize.Job]:
    inv = inventory.build(fx.store, inventory.pending_silos(fx.projects))
    return summarize.jobs_for(inv, (fx.store / "ROUTER.md").read_text(), ["alpha", "beta"])


def test_each_job_runs_isolated_and_is_cached(silos: Fixture, fake: Path):
    js = jobs(silos)
    assert [j.kind for j in js] == ["silo", "silo", "file", "file", "file"]
    res = summarize.run(silos.store, js, parallel=2)
    assert all(r["status"] == "ok" and not r["cached"] for r in res)
    assert res[0]["summary"]["territory_new"] == "fixture/alpha"
    assert res[2]["summary"]["conclusion"] == "Conclusion of deploy-notes.md"
    assert res[2]["tokens_in"] == 120 and res[2]["model"] == "claude-sonnet-fixture"
    for c in calls(fake):
        a = c["argv"]
        assert a[a.index("--tools") + 1] == "" and a[a.index("--setting-sources") + 1] == ""
        assert '"disableAllHooks": true' in a[a.index("--settings") + 1]
        assert "--no-session-persistence" in a and a[a.index("--model") + 1] == "sonnet"
        assert c["ls"] == [] and "mem-summarize-" in c["cwd"]    # an empty scratch cwd
    n = len(calls(fake))
    again = summarize.run(silos.store, jobs(silos))
    assert all(r["cached"] for r in again) and len(calls(fake)) == n


def test_a_changed_file_is_the_only_one_rerun(silos: Fixture, fake: Path):
    summarize.run(silos.store, jobs(silos))
    p = silos.projects / BETA / "memory" / "schema-notes.md"
    p.write_text(p.read_text() + "\nMore.\n")
    res = summarize.run(silos.store, jobs(silos))
    assert [r["id"] for r in res if not r["cached"]] == [f"{BETA}/schema-notes.md"]


def test_failures_retry_once_then_stay_failed(silos: Fixture, fake: Path):
    md = silos.projects / ALPHA / "memory"
    (md / "flaky.md").write_text("---\nname: flaky\ndescription: d\n---\n\nFAIL-ONCE\n")
    (md / "broken.md").write_text("---\nname: broken\ndescription: d\n---\n\nFAIL-ALWAYS\n")
    (md / "malformed.md").write_text("---\nname: malformed\ndescription: d\n---\n\nSCHEMA-BREAK\n")
    res = {r["id"].rsplit("/", 1)[-1]: r for r in summarize.run(silos.store, jobs(silos))}
    assert res["flaky.md"]["status"] == "ok"
    assert res["broken.md"]["status"] == "failed" and "exit 1" in res["broken.md"]["error"]
    assert res["malformed.md"]["status"] == "failed"
    assert "expected string" in res["malformed.md"]["error"]
    # a failure is not trusted from cache: the next run tries it again
    before = len(calls(fake))
    summarize.run(silos.store, jobs(silos))
    assert len(calls(fake)) - before == 4           # broken and malformed, twice each


def test_validate():
    schema = json.loads(summarize.AGENTS.joinpath("memory-summary.schema.json").read_text())
    ok = {"conclusion": "c", "description_verdict": "good", "kind": "record",
          "subject_repos": [], "territory_hint": None, "shape": ["index-only"], "verify": [],
          "obsolete": {"likely": False, "why": ""}, "confidence": "low"}
    assert summarize.validate(ok, schema) == []
    bad = {**ok, "kind": "nope", "extra": 1, "shape": ["wat"]}
    del bad["confidence"]
    errs = summarize.validate(bad, schema)
    assert len(errs) == 4, errs


def test_cli(silos: Fixture, fake: Path, tmp_path: Path):
    env = {**silos.env(), summarize.RUNNER_ENV: str(tmp_path / "fake-claude"),
           "FAKE_LOG": str(fake), "FAKE_STATE": str(tmp_path)}
    base = ["--root", str(silos.store), "--legacy", str(silos.projects)]
    rc, out, err = run(mem_cmd("migrate", "inventory", *base), env)
    assert rc == 0, err
    assert "alpha: 2 files" in out and "MIXED STATE ['kit-sync-v1']" in out
    assert (silos.store / ".cache" / "migrate" / "inventory.json").is_file()
    rc, out, _ = run(mem_cmd("migrate", "summarize", "--dry-run", "--silo", "alpha", *base), env)
    assert rc == 0 and out.startswith("3 to run, 0 cached") and not fake.exists()
    rc, out, err = run(mem_cmd("migrate", "summarize", "--silo", "alpha", *base), env)
    assert rc == 0, err
    assert "3 summaries: 3 run, 0 cached, 0 failed; $0.03" in out and "[3/3] ok" in err
    rc, out, _ = run(mem_cmd("migrate", "summaries", "--silo", "alpha", *base), env)
    assert rc == 0 and "-> NEW fixture/alpha" in out
    assert "Conclusion of deploy-notes.md" in out and "dated-snapshot" in out
    run(mem_cmd("migrate", "summarize", *base), env)
    rc, out, _ = run(mem_cmd("migrate", "summaries", "--silo", "alpha", "--silo", "beta", *base),
                     env)
    # files print under their own silo, not after the last one
    assert out.index("deploy-notes.md") < out.index(f"## {BETA}") < out.index("schema-notes.md")
    rc, out, _ = run(mem_cmd("migrate", "summaries", "--silo", "gone-repo", *base), env)
    assert rc == 0 and "## -Users-nobody-gone-repo" in out


def plan_for(fx: Fixture) -> tuple[dict, dict]:
    from claude_hybrid_memory.migrate import plan as P

    inv = inventory.build(fx.store, inventory.pending_silos(fx.projects))
    router = (fx.store / "ROUTER.md").read_text()
    js = summarize.jobs_for(inv, router)
    summarize.run(fx.store, js)
    return P.draft(fx.store, inv, summarize.cached(fx.store, js), router), inv


def test_map_draft(silos: Fixture, fake: Path):
    md = silos.projects / ALPHA / "memory"
    (md / "old-thing.md").write_text("---\nname: old-thing\ndescription: d\n---\n\nOBSOLETE-MARK\n")
    (md / "lab-note.md").write_text("---\nname: lab-note\ndescription: d\n---\n\nHINT-LAB\n")
    (md / "vague.md").write_text("---\nname: vague\ndescription: d\n---\n\nHINT-NOWHERE\n")
    (md / "fine.md").write_text("---\nname: fine\ndescription: d\n---\n\nGOOD-DESC\n")
    plan, _ = plan_for(silos)
    by = {s["silo"]: s for s in plan["silos"]}
    alpha, beta, gone = by[ALPHA], by[BETA], by["-Users-nobody-gone-repo"]
    assert alpha["territory"] == "fixture/alpha" and alpha["new"] is True
    assert beta["territory"] == "home/lab" and beta["new"] is False     # code decides
    assert gone["mode"] == "parked"                       # not on this disk is not dead
    assert any("mixed state" in x for x in gone["signals"])
    f = {x["file"]: x for x in alpha["files"]}
    assert f["deploy-notes.md"]["description"] == "proposed"
    assert f["deploy-notes.md"]["proposed"] == "Conclusion of deploy-notes.md"
    assert "mentions beta-repo" in f["deploy-notes.md"]["signals"]
    assert f["fine.md"]["description"] == "keep" and "proposed" not in f["fine.md"]
    assert f["old-thing.md"]["action"] == "archive" and f["old-thing.md"]["why"] == "retired"
    assert f["lab-note.md"]["action"] == "relocate" and f["lab-note.md"]["to"] == "home/lab"
    # a hint naming no real territory is a signal, never a relocation
    assert f["vague.md"]["action"] == "land" and "hint: the resume" in f["vague.md"]["signals"]


def test_map_check_and_approval(silos: Fixture, fake: Path):
    from claude_hybrid_memory.migrate import plan as P

    plan, inv = plan_for(silos)
    assert P.check(plan, inv, silos.store) == []
    ok = P.approve(plan)
    assert P.is_approved(ok)
    # advisory fields may change without voiding approval; decisions may not
    ok["silos"][0]["files"][0]["signals"] = ["anything"]
    assert P.is_approved(ok)
    ok["silos"][0]["files"][0]["action"] = "archive"
    assert not P.is_approved(ok)
    bad = P.approve(plan)
    s = bad["silos"][0]
    s["territory"] = "Not A Territory"
    s["files"][0]["action"] = "relocate"
    s["files"].append({"file": "ghost.md", "action": "land", "description": "keep"})
    dropped = s["files"].pop(1)
    errs = P.check(bad, inv, silos.store)
    assert any("is not an area/name" in e for e in errs)
    assert any("relocate needs `to:`" in e for e in errs)
    assert any("ghost.md: not in the inventory" in e for e in errs)
    assert any(f"{dropped['file']}: in the inventory, missing from the plan" in e for e in errs)


def test_map_cli_keeps_edits_and_enforces_approval(silos: Fixture, fake: Path, tmp_path: Path):
    from claude_hybrid_memory.migrate import plan as P

    env = {**silos.env(), summarize.RUNNER_ENV: str(tmp_path / "fake-claude"),
           "FAKE_LOG": str(fake), "FAKE_STATE": str(tmp_path)}
    base = ["--root", str(silos.store), "--legacy", str(silos.projects)]
    run(mem_cmd("migrate", "summarize", *base), env)
    rc, out, err = run(mem_cmd("migrate", "map", *base), env)
    assert rc == 0, err
    assert "drafted" in out and "fixture/alpha  (NEW, not in router)" in out
    assert "home/lab  (existing" in out and "not approved" in out
    f = P.path(silos.store)
    assert f.read_text().startswith("# The territory map")
    plan = P.load(silos.store)
    plan["silos"][0]["files"][0]["proposed"] = "Matt's own wording."
    P.write(silos.store, plan)
    rc, out, _ = run(mem_cmd("migrate", "map", *base), env)     # no redraft over edits
    assert "drafted" not in out and P.load(silos.store)["silos"][0]["files"][0]["proposed"] \
        == "Matt's own wording."
    rc, out, _ = run(mem_cmd("migrate", "map", "--approve", *base), env)
    assert rc == 0 and "approved" in out and P.is_approved(P.load(silos.store))
    plan = P.load(silos.store)
    plan["silos"][0]["territory"] = "fixture/elsewhere"
    P.write(silos.store, plan)
    rc, out, _ = run(mem_cmd("migrate", "map", *base), env)
    assert "edited since it was approved" in out
    rc, out, _ = run(mem_cmd("migrate", "map", "--rebuild", *base), env)
    assert "drafted" in out and f.with_name("plan.prev.yaml").is_file()


def git_init(root: Path) -> None:
    import subprocess

    for args in (["init", "-q"], ["config", "user.email", "fixture@example.invalid"],
                 ["config", "user.name", "Fixture"], ["add", "-A"],
                 ["commit", "-q", "-m", "Baseline"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    (root / ".gitignore").write_text(".cache/\n")


def subjects(root: Path) -> list[str]:
    import subprocess

    return subprocess.run(["git", "-C", str(root), "log", "--format=%s"], capture_output=True,
                          text=True).stdout.splitlines()


@pytest.fixture
def landed(silos: Fixture, fake: Path):
    """The fixture silos summarized, mapped and approved, ready for stage 4."""
    from claude_hybrid_memory.migrate import plan as P

    md = silos.projects / ALPHA / "memory"
    (md / "old-thing.md").write_text("---\nname: old-thing\ndescription: d\n---\n\nOBSOLETE-MARK\n")
    p = md / "deploy-notes.md"
    p.write_text(p.read_text() + "\nSee [[old-thing]] and [[user-profile]].\n")
    for d in (md, silos.projects / BETA / "memory"):
        (d / "user_profile.md").write_text(
            "---\nname: User profile\ndescription: who\nmetadata:\n  type: user\n---\n\nBody.\n")
    git_init(silos.store)
    plan, inv = plan_for(silos)
    P.write(silos.store, P.approve(plan))
    return silos


def apply_cli(fx: Fixture, fake: Path, *extra: str) -> tuple[int, str, str]:
    env = {**fx.env(), summarize.RUNNER_ENV: str(fake.parent / "fake-claude"),
           "FAKE_LOG": str(fake), "FAKE_STATE": str(fake.parent)}
    return run(mem_cmd("migrate", *extra, "--root", str(fx.store), "--legacy",
                       str(fx.projects)), env)


def test_apply_lands_each_silo_in_two_commits(landed: Fixture, fake: Path):
    fx = landed
    rc, out, err = apply_cli(fx, fake, "apply", "--dry-run")
    assert rc == 0, err
    assert "alpha-user-profile.md" in out and not (fx.store / "territories/fixture").exists()
    rc, out, err = apply_cli(fx, fake, "apply")
    assert rc == 0, out + err
    alpha = fx.store / "territories/fixture/alpha"
    # the file as it was, with only name and kind normalized, and its proposed description
    dn = (alpha / "deploy-notes.md").read_text()
    assert "Fixed in commit `abc1234`, see PR #12." in dn and "kind: territory" in dn
    assert 'description: "Conclusion of deploy-notes.md"' in dn
    up = (alpha / "alpha-user-profile.md").read_text()
    assert "name: alpha-user-profile" in up and "  type: user" in up
    # a slug in two silos is prefixed in both, and links follow it within the silo
    assert (fx.store / "territories/home/lab/lab-user-profile.md").is_file()
    assert "[[alpha-user-profile]]" in dn
    # archived, and the link into it points at the archive path rather than dangling
    assert (fx.store / "archive/fixture-alpha/old-thing.md").is_file()
    assert "old-thing" in (fx.store / "archive/fixture-alpha/WHY-ARCHIVED.md").read_text()
    assert "`archive/fixture-alpha/old-thing.md`" in dn and not (alpha / "old-thing.md").exists()
    index = (alpha / "MEMORY.md").read_text()
    assert "territory: fixture/alpha" in index and "alpha: {mode: parked}" in index
    assert "- [deploy-notes](deploy-notes.md) — Conclusion of deploy-notes.md" in index
    router = (fx.store / "ROUTER.md").read_text()
    assert "## fixture\n- fixture/alpha (" in router
    assert "- home/lab (" in router and "- home/lab (3)" not in router
    s = subjects(fx.store)
    assert f"migrate: land {ALPHA} as-is in fixture/alpha" in s
    assert s[0] == f"migrate: apply the plan's decisions for {BETA}"
    # the silo now routes to the territory; its files are kept beside it
    silo = fx.projects / ALPHA / "memory"
    assert silo.is_symlink() and silo.resolve() == alpha.resolve()
    assert (fx.projects / ALPHA / "memory.premigration" / "deploy-notes.md").is_file()
    rc, out, _ = apply_cli(fx, fake, "apply")                  # nothing left to land
    assert rc == 0 and "0 silo(s) landed" in out


def test_undo_puts_a_silo_back(landed: Fixture, fake: Path):
    fx = landed
    apply_cli(fx, fake, "apply")
    rc, out, err = apply_cli(fx, fake, "undo", "--silo", "beta")
    assert rc == 0, err
    assert not (fx.store / "territories/home/lab/lab-user-profile.md").exists()
    silo = fx.projects / BETA / "memory"
    assert silo.is_dir() and not silo.is_symlink()
    assert not (fx.projects / BETA / "memory.premigration").exists()
    assert subjects(fx.store)[0].startswith('Revert "migrate: land ' + BETA)
    # a silo sharing a territory with a later one conflicts; nothing is changed
    head = subjects(fx.store)[0]
    rc, _, err = apply_cli(fx, fake, "undo", "--silo", "gone-repo")
    assert rc == 1 and "nothing changed" in err and subjects(fx.store)[0] == head
    rc, out, _ = apply_cli(fx, fake, "apply", "--silo", "beta")      # and it lands again
    assert rc == 0 and "landed" in out


def test_apply_refuses_an_unapproved_plan(landed: Fixture, fake: Path):
    from claude_hybrid_memory.migrate import plan as P

    plan = P.load(landed.store)
    plan["silos"][0]["files"][0]["action"] = "archive"
    P.write(landed.store, plan)
    rc, _, err = apply_cli(landed, fake, "apply")
    assert rc == 1 and "not approved" in err
    assert not (landed.store / "territories/fixture").exists()


def test_refine_queue_derives_and_drops(landed: Fixture, fake: Path):
    """Every item comes from the store, the summaries or the audit, and working it is what
    removes it: there is no done-list to keep in step."""
    from claude_hybrid_memory.migrate import plan as P
    from claude_hybrid_memory.migrate import queue

    fx = landed
    md = fx.projects / ALPHA / "memory"
    p = md / "deploy-notes.md"
    p.write_text(p.read_text() + "VERIFY-MARK\n")
    (md / "house-rule.md").write_text(
        "---\nname: house-rule\ndescription: d\n---\n\nSTANDING-MARK LOW-CONF\n")
    plan, _ = plan_for(fx)
    for s in plan["silos"]:                     # keep one names-subject description as it was
        for e in s["files"]:
            if e["file"] == "house-rule.md":
                e["description"] = "keep"
    P.write(fx.store, P.approve(plan))
    rc, out, err = apply_cli(fx, fake, "apply")
    assert rc == 0, out + err

    def items() -> dict[str, dict]:
        return {i["key"]: i for i in queue.build(fx.store, fx.projects)["items"]}

    alpha = "territories/fixture/alpha"
    q = items()
    dn, hr = f"{alpha}/deploy-notes.md", f"{alpha}/house-rule.md"
    assert q[f"verify:{dn}"]["source"] == "summary+heuristic"      # abc1234 in the body too
    assert "abc1234" in q[f"verify:{dn}"]["detail"]
    assert {f"shape:{dn}", f"standing-candidate:{hr}", f"description:{hr}",
            f"low-confidence:{hr}"} <= q.keys()
    assert not any(k.endswith("launch-record.md") and k.startswith("verify") for k in q)
    ranks = [i["rank"] for i in queue.build(fx.store, fx.projects)["items"]]
    assert ranks == sorted(ranks)
    assert next(iter(q)) == f"standing-candidate:{hr}"             # promotions lead

    # working an item is what drops it
    f = fx.store / dn
    f.write_text(f.read_text().replace("---\n\n", "---\n\nRewritten. ", 1)
                 .replace("name: deploy-notes", "name: deploy-notes\nverify: true", 1))
    h = fx.store / hr
    h.write_text(h.read_text().replace("description: d", "description: A house rule"))
    q = items()
    assert f"shape:{dn}" not in q and f"verify:{dn}" not in q
    assert f"description:{hr}" not in q and f"standing-candidate:{hr}" in q
    (fx.store / "standing").mkdir(exist_ok=True)
    h.replace(fx.store / "standing" / "house-rule.md")             # promoted
    assert not any(k.endswith(hr) for k in items())

    # a declined item is suppressed by its key in RETRO.md, and counted
    key = next(iter(items()))
    (fx.store / "RETRO.md").write_text(f"- `refine:{key}` - Matt: fine as it is\n")
    q = queue.build(fx.store, fx.projects)
    assert key not in {i["key"] for i in q["items"]} and q["declined"] == 1


def test_refine_queue_cli(landed: Fixture, fake: Path):
    fx = landed
    apply_cli(fx, fake, "apply")
    env = fx.env()
    base = ["--root", str(fx.store), "--legacy", str(fx.projects)]
    rc, out, err = run(mem_cmd("refine", "queue", *base), env)
    assert rc == 0, err
    assert "item(s)" in out and "[shape] territories/fixture/alpha/" in out
    assert (fx.store / ".cache/migrate/queue.json").is_file()
    rc, out, _ = run(mem_cmd("refine", "queue", "--territory", "home/lab", "--json", *base), env)
    q = json.loads(out)
    assert rc == 0 and q["items"] and all(i["territory"] == "home/lab" for i in q["items"])


def test_refine_queue_finds_undated_memories_in_active_territories(fx: Fixture):
    """No status, never verified, no recipe: the audit calls that `slow` and only `stale`,
    and with no summary nothing else queues it, so a territory carried over from an early
    store looked clean while most of it was undated."""
    from claude_hybrid_memory.migrate import queue

    index = fx.store / "territories/console/kit/MEMORY.md"
    head = "---\nterritory: console/kit\n"
    index.write_text(index.read_text().replace(
        head, head + "members:\n  kit-repo: {owner: self, mode: active}\n", 1))

    def undated() -> set[str]:
        return {i["path"].rsplit("/", 1)[-1] for i in queue.build(fx.store, fx.projects)["items"]
                if i["type"] == "unverified"}

    # kit-sync-v1 is undated too, but superseded; home/lab has no active member
    assert undated() == {"kit_raw_notes.md", "kit-unlisted-orphan.md"}
    orphan = fx.store / "territories/console/kit/kit-unlisted-orphan.md"
    orphan.write_text(orphan.read_text().replace("volatility: live", "last_verified: 2026-10-01"))
    assert undated() == {"kit_raw_notes.md"}
    index.write_text(index.read_text().replace("mode: active", "mode: parked"))
    assert undated() == set()


@pytest.mark.parametrize("entry", ["- home/kiln : The kiln. PULL WHEN: any of it.",
                                   "- home/lathe, home/kiln : PULL WHEN: in that repo."])
def test_router_line_leaves_a_hand_written_entry_alone(tmp_path: Path, entry: str):
    router = f"# MEMORY ROUTER\n\n## home\nStandalone.\n\n{entry}\n\n## fixture\n"
    (tmp_path / "ROUTER.md").write_text(router)
    (tmp_path / "territories/home/kiln").mkdir(parents=True)
    (tmp_path / "territories/home/kiln/MEMORY.md").write_text("# home/kiln\n")
    assert apply.router_line(tmp_path, "home/kiln", "subject") is None
    assert (tmp_path / "ROUTER.md").read_text() == router


def test_router_line_does_not_mistake_a_longer_name(tmp_path: Path):
    (tmp_path / "ROUTER.md").write_text("# MEMORY ROUTER\n\n## home\n- home/kiln-old : x.\n")
    (tmp_path / "territories/home/kiln").mkdir(parents=True)
    assert apply.router_line(tmp_path, "home/kiln", "subject") == "ROUTER.md: added home/kiln"
    assert "- home/kiln (0) : subject." in (tmp_path / "ROUTER.md").read_text()
