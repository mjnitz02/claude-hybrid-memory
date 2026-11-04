"""`mem new`: the write path that keeps a session off the harness's auto-memory recipe."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

from conftest import Fixture, mem_cmd, run

from claude_hybrid_memory import render
from claude_hybrid_memory.store import parse_frontmatter

KIT = "territories/console/kit"


def new(fx: Fixture, *args: str, body: str = "The body.\n", cwd: Path | None = None):
    """`mem new`, passing `-v live` unless the test names its own volatility, status or
    record flag: the requirement has a test of its own."""
    if not {"-v", "--volatility", "-s", "--status", "--record"} & set(args):
        args = (*args, "-v", "live")
    p = subprocess.run(mem_cmd("new", *args), input=body, capture_output=True, text=True,
                       env=fx.env(), cwd=cwd or fx.repo, timeout=60)
    return p.returncode, p.stdout, p.stderr


def test_new_writes_store_frontmatter_and_indexes_a_hand_written_territory(fx: Fixture):
    rc, out, err = new(fx, "kit-card-reader", "-d", "The built-in reader panics; use USB.",
                       "-g", "Hardware")
    assert rc == 0, err
    assert f"wrote {KIT}/kit-card-reader.md" in out
    # a hand-written index can't honour -g, and says so instead of "indexed it"
    assert "indexed it" not in out and "--group 'Hardware' was NOT honoured" in out
    assert "mem render console/kit --adopt" in out
    assert "byte" not in out and "cap" not in out           # nothing about size, ever
    text = (fx.store / KIT / "kit-card-reader.md").read_text()
    meta, body, problems = parse_frontmatter(text)
    assert not problems and body.strip() == "The body."
    assert meta == {"name": "kit-card-reader",
                    "description": "The built-in reader panics; use USB.",
                    "kind": "territory", "role": "reference", "volatility": "live",
                    "last_verified": dt.date.today().isoformat(), "group": "Hardware"}
    # console/kit is hand-written in the fixture: it gains a bare line, after the last entry
    idx = (fx.store / KIT / "MEMORY.md").read_text()
    assert "- kit-card-reader: The built-in reader panics; use USB.\n" in idx
    assert idx.index("kit-gone-file") < idx.index("kit-card-reader")
    # and nothing a session runs afterwards complains about it
    rc, out, _ = run(mem_cmd("audit", "--json", "--scan", "store"), fx.env())
    assert not [f for f in json.loads(out) if "kit-card-reader" in f["path"]]


def test_new_re_renders_a_rendered_territory(fx: Fixture):
    rc, _, err = run(mem_cmd("render", "console/kit", "--adopt", "--write"), fx.env())
    assert rc == 0, err
    rc, out, err = new(fx, "kit-probe", "-d", "The probe works.", "--record")
    assert rc == 0, err
    assert "indexed it in console/kit/MEMORY.md" in out
    idx = (fx.store / KIT / "MEMORY.md").read_text()
    s, e = render.markers(idx)
    assert "kit-probe" in idx[s:e] and "kit-probe" not in idx[e:]
    assert "tier: record" in (fx.store / KIT / "kit-probe.md").read_text()
    assert [f for f in render.check(fx.store, ["console/kit"]) if f.code == "render-stale"] == []


def test_new_refuses_and_writes_nothing(fx: Fixture):
    before = sorted(p.name for p in (fx.store / KIT).iterdir())
    for args, why in [(("kit-sync-design", "-d", "x"), "already exists"),
                      (("Bad_Slug", "-d", "x"), "kebab-case"),
                      (("kit-ok", "-d", "  "), "description"),
                      (("kit-ok", "-d", "x", "-t", "no/such"), "no territory")]:
        rc, _, err = new(fx, *args)
        assert rc == 2 and why in err, (args, err)
    rc, _, err = new(fx, "kit-ok", "-d", "x", body="")
    assert rc == 2 and "stdin" in err
    rc, _, err = new(fx, "kit-ok", "-d", "x", cwd=fx.elsewhere)
    assert rc == 2 and "--territory" in err
    assert sorted(p.name for p in (fx.store / KIT).iterdir()) == before


def test_new_takes_territory_from_the_flag_anywhere(fx: Fixture):
    rc, _, err = new(fx, "lab-disk-spin", "-d", "Disks park after 60 minutes.",
                     "-t", "home/lab", cwd=fx.elsewhere)
    assert rc == 0, err
    assert "- lab-disk-spin: Disks park after 60 minutes." in (
        fx.store / "territories/home/lab/MEMORY.md").read_text()


def test_new_never_relists_a_superseded_memory(fx: Fixture):
    """console/kit's hand-written index omits nothing, so drop kit-sync-v1's line: it is
    superseded, and indexing a new memory must not bring it back."""
    idx = fx.store / KIT / "MEMORY.md"
    idx.write_text(idx.read_text().replace("- [Sync v1](kit-sync-v1.md) — the first cut.\n", ""))
    rc, _, err = new(fx, "kit-probe", "-d", "The probe works.")
    assert rc == 0, err
    assert "kit-sync-v1" not in idx.read_text()


def test_new_requires_volatility_or_status_unless_a_record(fx: Fixture):
    """The writing session knows whether it is recording state or a fact, and that sets how
    long a later session can act on the claim before checking it."""
    before = sorted(p.name for p in (fx.store / KIT).iterdir())
    p = subprocess.run(mem_cmd("new", "kit-no-vol", "-d", "x"), input="Body.\n",
                       capture_output=True, text=True, env=fx.env(), cwd=fx.repo, timeout=60)
    assert p.returncode == 2 and "--volatility" in p.stderr
    assert sorted(p.name for p in (fx.store / KIT).iterdir()) == before

    rc, _, err = new(fx, "kit-shipped", "-d", "x", "-s", "SHIPPED")
    assert rc == 0, err
    meta = parse_frontmatter((fx.store / KIT / "kit-shipped.md").read_text())[0]
    assert meta["status"] == "SHIPPED" and "volatility" not in meta     # the status implies it

    rc, _, err = new(fx, "kit-a-run", "-d", "x", "--record")
    assert rc == 0, err
    meta = parse_frontmatter((fx.store / KIT / "kit-a-run.md").read_text())[0]
    assert meta["tier"] == "record" and "volatility" not in meta


def test_the_help_example_runs_as_typed(fx: Fixture):
    # The example broke twice: once missing the then-new -v, once naming a group no store
    # has after -g became strict. Run it straight out of --help, in a rendered territory.
    import shlex
    rc, _, err = run(mem_cmd("render", "console/kit", "--adopt", "--write"), fx.env())
    assert rc == 0, err
    p = subprocess.run(mem_cmd("new", "--help"), capture_output=True, text=True, env=fx.env())
    line = next(ln for ln in p.stdout.splitlines() if ln.startswith("example: mem new "))
    argv = shlex.split(line.removeprefix("example: mem new ").split("<<")[0])
    rc, out, err = new(fx, *argv)
    assert rc == 0, err
    assert "indexed it" in out
