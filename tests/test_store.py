from __future__ import annotations

from pathlib import Path

from conftest import Fixture

from claude_hybrid_memory.store import load_file, parse_frontmatter, scan_legacy, scan_store


def test_nested_metadata_is_hoisted():
    meta, body, _ = parse_frontmatter(
        "---\nname: a-b\nmetadata: \n  type: project\n  originSessionId: x\n---\n\nBody\n")
    assert meta["metadata"] == {"type": "project", "originSessionId": "x"}
    assert meta["type"] == "project"
    assert body == "Body\n"


def test_top_level_wins_over_hoisted():
    meta, _, _ = parse_frontmatter("---\nmetadata: \n  type: project\ntype: other\n---\n")
    assert meta["type"] == "other"


def test_keyless_line_is_skipped_not_fatal(fx: Fixture):
    # tag-test-fodder-corpus.md's shape: a frontmatter line with no key
    m = load_file(fx.store / "territories/console/kit/kit-fodder-corpus.md", "store", "console/kit")
    assert m.meta["verify"] == "test -d /nonexistent/fixture/corpus"
    assert m.meta["last_verified"] == "2024-09-15"
    assert not any(k.startswith("exit") for k in m.meta)
    assert len(m.fm_problems) == 1 and "not valid YAML" in m.fm_problems[0]


def test_no_frontmatter():
    assert parse_frontmatter("# just a heading\n") == ({}, "# just a heading\n", [])
    assert parse_frontmatter("---\nunterminated: yes\n") == ({}, "---\nunterminated: yes\n", [])
    assert parse_frontmatter("---\n---\nBody\n") == ({}, "Body\n", [])


# The shapes below are the ones strict YAML disagreed with on the personal Mac's 409 real
# frontmatter blocks (2026-10-21); each names the file it reproduces.

def test_unquoted_hash_keeps_the_full_value():
    # memoryecho-capture.md: YAML alone cut 174 chars down to "Capture is the"
    meta, _, problems = parse_frontmatter(
        "---\nname: x-y\n"
        "description: SHIPPED 2026-08-04 (PR #12) - capture lives at the root\n---\n")
    assert meta["description"] == "SHIPPED 2026-08-04 (PR #12) - capture lives at the root"
    assert len(problems) == 1 and "`description:`" in problems[0]


def test_unquoted_colon_falls_back_and_says_so():
    # ios-codeql-and-scanning.md: `build-mode: manual` inside an unquoted description
    meta, _, problems = parse_frontmatter(
        "---\nname: x-y\ndescription: RESOLVED - `build-mode: manual` is merged\n"
        "last_verified: 2026-10-02\n---\n")
    assert meta["name"] == "x-y" and meta["last_verified"] == "2026-10-02"
    assert meta["description"].startswith("RESOLVED")
    assert len(problems) == 1 and "not valid YAML" in problems[0]


def test_yaml_reads_quoting_the_hand_parser_got_wrong():
    # undumped-observation-is-evidence.md: the old strip("\"'") ate the closing quote;
    # jai-proxy-card-recheck.md: escaped quotes came through with their backslashes
    meta, _, problems = parse_frontmatter(
        "---\ndescription: \"treat 'we have no data'\"\nexpect: \"not to \\\"fix\\\"\"\n---\n")
    assert meta["description"] == "treat 'we have no data'"
    assert meta["expect"] == 'not to "fix"'
    assert problems == []


def test_dates_stay_text_and_bad_ones_do_not_raise():
    meta, _, problems = parse_frontmatter(
        "---\nlast_verified: 2026-13-45\nother: 2026-10-02\n---\n")
    assert meta == {"last_verified": "2026-13-45", "other": "2026-10-02"} and problems == []


def test_volatility_derives_from_status(fx: Fixture):
    m = load_file(fx.store / "territories/home/lab/lab-ssh-read-only.md", "store", "home/lab")
    assert m.volatility == "stable"


def test_wikilink_buckets(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("[[real-slug]] [[ var ]] [[override]] [[Not A Slug]] [[]]")
    m = load_file(p, "store", "t")
    assert m.links == ["real-slug"]
    assert m.maybe == ["override"]
    assert m.nonlinks == ["var", "Not A Slug"]


def test_scan_store_skips_routers_and_exports(fx: Fixture):
    mems, routers = scan_store(fx.store)
    assert set(routers) == {"home/lab", "console/kit"}
    names = {m.path.name for m in mems}
    assert "MEMORY.md" not in names and "EXPORTS.md" not in names
    assert {m.container for m in mems} == {"home/lab", "console/kit", "standing"}


def test_scan_legacy_skips_symlinked_silos(fx: Fixture):
    mems, routers = scan_legacy(fx.projects)
    assert {m.container for m in mems} == {"-Users-nobody-gone-repo"}
    assert set(routers) == {"-Users-nobody-gone-repo"}
