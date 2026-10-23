from __future__ import annotations

import re
from pathlib import Path

from conftest import Fixture

from claude_hybrid_memory.hooks import session_start


def standing(tmp_path: Path, name: str, desc: str, body: str) -> Path:
    p = tmp_path / f"{name}.md"
    p.write_text(f"---\nname: {name}\nkind: standing\ndescription: {desc}\n---\n\n{body}\n")
    return p


def test_directive_text_drops_frontmatter(tmp_path: Path):
    p = standing(tmp_path, "a-b", "The conclusion.", "Why and how.")
    assert session_start.directive_text(p) == "## The conclusion.\n\nWhy and how."
    assert session_start.directive_desc(p) == "## The conclusion."


def test_fit_untouched_when_it_fits(tmp_path: Path):
    s = [standing(tmp_path, "a-b", "A.", "body")]
    text, notes = session_start.fit(["MACHINE", "GATES"], s, "## r\nmap", "")
    assert notes == [] and "body" in text


def test_fit_degrades_biggest_directive_first(tmp_path: Path, monkeypatch):
    small = standing(tmp_path, "small-one", "Small.", "s" * 50)
    big = standing(tmp_path, "big-one", "Big.", "b" * 2000)
    monkeypatch.setattr(session_start, "MAX_CHARS", 1500)
    text, notes = session_start.fit(["MACHINE"], [small, big], "## r\nmap", "")
    assert "s" * 50 in text and "b" * 2000 not in text and "## Big." in text
    assert "`big-one`" in notes[0] and "small-one" not in notes[0]


def test_fit_never_cuts_protected_and_drops_router_tail(tmp_path: Path, monkeypatch):
    s = [standing(tmp_path, "a-b", "A.", "a" * 500)]
    router = "## first\n" + "f" * 400 + "\n## second\n" + "g" * 400 + "\n## third\n" + "h" * 400
    protected = ["MACHINE " + "m" * 300, "GATES " + "x" * 300]
    monkeypatch.setattr(session_start, "MAX_CHARS", 1200)
    text, notes = session_start.fit(protected, s, router, "")
    assert all(p in text for p in protected)
    assert "## first" in text and "## third" not in text
    assert "third" in notes[-1]


def test_territory_for_symlinked_silo(fx: Fixture, monkeypatch):
    monkeypatch.setattr(session_start, "PROJECTS", fx.projects)
    terr, all_t = session_start.territory_for(fx.repo / "src", fx.store)
    assert terr == "console/kit"
    assert all_t == ["console/kit", "home/lab"]
    assert session_start.territory_for(fx.elsewhere, fx.store)[0] is None


def test_retro_overdue():
    assert session_start.retro_overdue("last_retrospective: 2000-01-01\n") > 30
    assert session_start.retro_overdue("no date here") is None


def test_territory_for_matches_harness_encoding(fx: Fixture, monkeypatch, tmp_path: Path):
    repo = (tmp_path / "iCloud~md~my vault@x_y").resolve()
    (repo / ".git").mkdir(parents=True)
    silo = fx.projects / ("-" + "-".join(
        re.sub(r"[^A-Za-z0-9]", "-", part) for part in repo.parts[1:]))
    silo.mkdir()
    (silo / "memory").symlink_to(fx.store / "territories" / "home" / "lab")
    monkeypatch.setattr(session_start, "PROJECTS", fx.projects)
    assert session_start.territory_for(repo, fx.store)[0] == "home/lab"
