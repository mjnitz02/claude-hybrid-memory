from __future__ import annotations

import os

from conftest import Fixture, mem_cmd, run

from claude_hybrid_memory import cache
from claude_hybrid_memory.store import scan_store


def index(fx: Fixture):
    conn = cache.connect(fx.store)
    return conn, cache.refresh(conn, fx.store)


def test_index_covers_what_the_audit_scans_plus_archive(fx: Fixture):
    _, st = index(fx)
    mems, _ = scan_store(fx.store)
    assert st.by_area["territory"] + st.by_area["standing"] == len(mems)
    assert st.by_area["archive"] == 2
    assert cache.db_path(fx.store).is_file()


def test_refresh_is_incremental(fx: Fixture):
    conn, st = index(fx)
    total = st.files
    assert cache.refresh(conn, fx.store).unchanged == total

    p = fx.store / "territories/console/kit/kit-sync-v1.md"
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 10**9))
    st = cache.refresh(conn, fx.store)
    assert (st.touched, st.updated) == (1, 0)

    p.write_text(p.read_text() + "\nNow mentions a zeppelin.\n")
    st = cache.refresh(conn, fx.store)
    assert st.updated == 1
    # kit-sync-v1 is superseded by kit-sync-design, so it is only found when asked for
    assert [h.slug for h in cache.find(conn, ["zeppelin"], include_superseded=True).hits] == [
        "kit-sync-v1"
    ]

    p.unlink()
    st = cache.refresh(conn, fx.store)
    assert st.removed == 1 and st.files == total - 1
    assert cache.find(conn, ["zeppelin"], include_superseded=True).hits == []


def test_find_names_the_matching_section_and_its_line(fx: Fixture):
    conn, _ = index(fx)
    hits, _, _, partial, _ = cache.find(conn, ["03:00"])
    assert not partial and [h.slug for h in hits] == ["lab-backup-plan"]
    heading, line = hits[0].sections[0]
    lines = (fx.store / hits[0].path).read_text().split("\n")
    assert heading == "Current" and lines[line - 1] == "## Current"


def test_find_hides_archive_but_counts_it(fx: Fixture):
    conn, _ = index(fx)
    hits, hidden, _, _, _ = cache.find(conn, ["nightly"])
    assert hidden == 2 and all(h.area != "archive" for h in hits)
    hits, hidden, _, _, _ = cache.find(conn, ["nightly"], include_archive=True)
    assert hidden == 0 and {"kit-legacy-sync", "README"} <= {h.slug for h in hits}


def test_find_needs_every_term_before_it_falls_back(fx: Fixture):
    conn, _ = index(fx)
    hits, _, _, partial, _ = cache.find(conn, ["nightly", "verified"])
    assert not partial and [h.slug for h in hits] == ["lab-backup-plan"]
    hits, _, _, partial, _ = cache.find(conn, ["nightly", "zeppelin"])
    assert partial and hits


def test_find_territory_filter_includes_children(fx: Fixture):
    conn, _ = index(fx)

    def where(t):
        return {h.container for h in cache.find(conn, ["sync"], territory=t)[0]}

    assert where("console") == where("console/kit") == {"console/kit"}
    assert where("cons") == set()  # a path segment, not a string prefix
    assert where("home") == {"home/lab"}


def test_fts_syntax_in_input_is_inert(fx: Fixture):
    conn, _ = index(fx)
    for terms in (['"'], ["AND"], ["NEAR(", "*"], ["kit-sync", "OR"], ["", "  "]):
        cache.find(conn, terms)  # never raises


def test_sections_skip_fenced_headings_and_keep_file_lines():
    text = (
        "---\nname: a-b\n---\n\nIntro line.\n\n## Real\n\n```sh\n# not a heading\n```\n"
        "\n### Sub\n\ntext\n"
    )
    secs = cache.sections_of(text)
    assert [(s.level, s.heading) for s in secs] == [(0, ""), (2, "Real"), (3, "Sub")]
    lines = text.split("\n")
    assert lines[secs[1].line - 1] == "## Real" and lines[secs[2].line - 1] == "### Sub"
    assert "# not a heading" in secs[1].text


def test_schema_change_rebuilds(fx: Fixture):
    conn, st = index(fx)
    conn.execute("PRAGMA user_version = 0")
    conn.close()
    conn = cache.connect(fx.store)
    assert cache.refresh(conn, fx.store).added == st.files


def test_show_cli(fx: Fixture):
    root = ["--root", str(fx.store)]
    rc, out, _ = run(mem_cmd("show", "lab-backup-plan", *root), fx.env())
    assert rc == 0 and "nightly backups, verified by hand" in out and "Nightly at 03:00." in out
    rc, out, _ = run(mem_cmd("show", "lab-backup-plan", "--section", "hist", *root), fx.env())
    assert rc == 0 and out.split("\n")[2] == "## History" and "Nightly" not in out
    rc, _, err = run(mem_cmd("show", "README", *root), fx.env())
    assert rc == 0  # one README in this fixture, so not ambiguous
    (fx.store / "territories/home/lab/kit-sync-v1.md").write_text(
        "---\nname: kit-sync-v1\ndescription: a namesake\n---\n"
    )
    rc, _, err = run(mem_cmd("show", "kit-sync-v1", *root), fx.env())
    assert rc == 2 and "console/kit/kit-sync-v1" in err and "home/lab/kit-sync-v1" in err
    rc, out, _ = run(mem_cmd("show", "home/lab/kit-sync-v1", *root), fx.env())
    assert rc == 0 and "a namesake" in out
    rc, _, err = run(mem_cmd("show", "no-such-thing", *root), fx.env())
    assert rc == 2 and "mem find" in err


def test_find_cli_reports_hidden_archive(fx: Fixture):
    rc, out, _ = run(mem_cmd("find", "nightly", "--root", str(fx.store)), fx.env())
    assert rc == 0 and "lab-backup-plan" in out and "2 matches in archive/ not shown" in out


# --- find, as reworked after the 2026-11-04 usability eval ---------------------------------
# Synthetic fixtures. The eval's real failures (`find "card reader"`, `find delet`,
# `find sillytavern docker unraid`) are rerun against a scratch copy of the real store as the
# acceptance check; these pin the rules that fixed them.


def _mem(fx: Fixture, terr: str, slug: str, desc: str, body: str, **meta) -> None:
    extra = "".join(f"{k}: {v}\n" for k, v in meta.items())
    (fx.store / "territories" / terr / f"{slug}.md").write_text(
        f"---\nname: {slug}\nkind: territory\ndescription: {desc}\n{extra}---\n\n{body}\n"
    )


def test_find_splits_an_argument_into_words_that_may_sit_in_different_sections(fx: Fixture):
    _mem(
        fx,
        "console/kit",
        "kit-sd-panic",
        "The built-in slot panics under load.",
        "## Hardware\n\nThe SD card goes in the side.\n\n## Fix\n\nUse the USB reader.",
        volatility="stable",
        last_verified="2026-11-01",
    )
    conn, _ = index(fx)
    found = cache.find(conn, ["card reader"])  # one argument, two words, two sections
    assert not found.partial and [h.slug for h in found.hits] == ["kit-sd-panic"]


def test_find_matches_words_as_prefixes(fx: Fixture):
    _mem(
        fx,
        "console/kit",
        "kit-no-deletions",
        "Never run deletions yourself.",
        "List them.",
        volatility="stable",
        last_verified="2026-11-01",
    )
    conn, _ = index(fx)
    assert "kit-no-deletions" in {h.slug for h in cache.find(conn, ["delet"]).hits}


def test_find_labels_a_single_argument_partial_when_no_memory_has_every_word(fx: Fixture):
    conn, _ = index(fx)
    found = cache.find(conn, ["nightly zeppelin"])  # used to be one phrase: "no matches"
    assert found.partial and found.hits and all(h.matched == 1 for h in found.hits)


def test_find_ranks_records_and_historical_below_current_state(fx: Fixture):
    body = "Docker on the unraid box, and the sillytavern container."
    _mem(
        fx,
        "home/lab",
        "lab-st-now",
        "Where ST runs today.",
        body,
        volatility="slow",
        last_verified="2026-11-01",
    )
    for slug in ("lab-st-record-a", "lab-st-record-b"):
        _mem(
            fx,
            "home/lab",
            slug,
            "Where ST ran, sillytavern docker unraid.",
            body * 3,
            tier="record",
        )
    _mem(
        fx,
        "home/lab",
        "lab-st-old",
        "Where ST ran, sillytavern docker unraid.",
        body * 3,
        status="HISTORICAL",
        last_verified="2026-11-01",
    )
    conn, _ = index(fx)
    hits = cache.find(conn, ["sillytavern", "docker", "unraid"]).hits
    assert hits[0].slug == "lab-st-now"


def test_find_counts_full_matches_outside_an_empty_territory(fx: Fixture):
    conn, _ = index(fx)
    found = cache.find(conn, ["fodder"], territory="home/lab")
    assert found.hits == [] and found.elsewhere >= 1


def test_find_flags_a_memory_past_its_window(fx: Fixture):
    import datetime as dt

    _mem(
        fx,
        "home/lab",
        "lab-old-claim",
        "A live claim, long unchecked.",
        "Body.",
        volatility="live",
        last_verified="2026-09-11",
    )
    _mem(
        fx,
        "home/lab",
        "lab-fresh-claim",
        "A live claim, checked.",
        "Body.",
        volatility="live",
        last_verified="2026-11-01",
    )
    conn, _ = index(fx)
    due = {h.slug: h.due for h in cache.find(conn, ["claim"], today=dt.date(2026, 11, 4)).hits}
    assert due == {"lab-old-claim": "PAST WINDOW 54d > 14d live", "lab-fresh-claim": ""}


def test_find_puts_a_standing_directive_first_when_its_headline_matches(fx: Fixture):
    # Synthetic, in the real failure's shape: a dozen territory memories say "delete" in
    # their description and repeat it in the body; the standing rule says it once. BM25
    # alone ranked the real rule 13th (independent review, 2026-11-04).
    for i in range(12):
        _mem(
            fx,
            "console/kit",
            f"kit-delete-{i}",
            "DELETES the old file on install.",
            "Delete. Deleted. Deletion. " * 5,
            volatility="slow",
            last_verified="2026-11-01",
        )
    (fx.store / "standing/hands-off-deletions.md").write_text(
        "---\nname: hands-off-deletions\nkind: standing\ndescription: For deletions, hand "
        "over a list.\nvolatility: stable\nlast_verified: 2026-11-01\n---\n\nReview first.\n"
    )
    (fx.store / "standing/mentions-in-passing.md").write_text(
        "---\nname: mentions-in-passing\nkind: standing\ndescription: Something else.\n"
        "volatility: stable\nlast_verified: 2026-11-01\n---\n\nOnce deleted a thing.\n"
    )
    conn, _ = index(fx)
    slugs = [h.slug for h in cache.find(conn, ["delet"], limit=5).hits]
    assert slugs[0] == "hands-off-deletions"
    assert "mentions-in-passing" not in slugs  # a body mention earns no lift
