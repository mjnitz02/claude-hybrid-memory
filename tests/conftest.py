"""Fixture stores: synthetic content, real shapes.

The repo crosses machines and memory content may not, so nothing here is copied from a real
store. Each fixture file instead reproduces a SHAPE found in a real store on
2026-10-21, and says which one. A test built on a shape nobody has seen proves only that the
test agrees with itself.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from claude_hybrid_memory.harness import silo_name

REPO = Path(__file__).resolve().parents[1]


FILES = {
    "MACHINE.md": "# MACHINE\n\nmachine: **fixture-mac**\n",
    "GATES.md": "# GATES\n\n- **The lab box is READ-ONLY.** → `home/lab`\n",
    "ROUTER.md": (
        "# MEMORY ROUTER\n\nmachine: fixture-mac\nlast_retrospective: 2026-08-01\n\n"
        "## home — the lab\n- home/lab (2) : lab-config.\n  PULL WHEN: the lab box.\n\n"
        "## console — the kit\n- console/kit (6) : kit-tools.\n  PULL WHEN: card work.\n"
    ),
    "RETRO.md": "# RETRO\n",
    # standing/: description-as-conclusion, which is what degradation falls back to
    "standing/use-uv-everywhere.md": (
        "---\nname: use-uv-everywhere\nkind: standing\n"
        "description: Every Python invocation goes through uv.\nvolatility: stable\n---\n\n"
        "**Why:** bare python fails on version mismatches.\n\n**How to apply:** `uv run`.\n"
    ),
    "standing/working-register.md": (
        "---\nname: working-register\nkind: standing\n"
        "description: Keep the register lively after a mistake.\n---\n\nBody text.\n"
    ),
    # home/lab exports two contracts; console/kit consumes it and inlines only one of them
    "territories/home/lab/MEMORY.md": (
        "---\nterritory: home/lab\nconsumes: none\nconsumed_by: console/kit\n---\n# home/lab\n\n"
        "## GATES\n\n**Read-only box.** → [[lab-ssh-read-only]]\n\n## MEMORIES\n"
        "- [Backup plan](lab-backup-plan.md) — nightly, verified by hand.\n"
    ),
    "territories/home/lab/EXPORTS.md": (
        "# home/lab — EXPORTS\n\n- SSH to the lab box is READ-ONLY, never mutate state\n"
        "- The array parks disks after 60 minutes, so the first read stalls silently\n"
    ),
    "territories/home/lab/lab-ssh-read-only.md": (
        "---\nname: lab-ssh-read-only\nkind: territory\nrole: gate\n"
        "description: Never write to the lab box over SSH.\nstatus: SHIPPED\n"
        "last_verified: 2026-10-01\n---\n\nThe login is root and technically can.\n"
    ),
    # the real migrated-legacy shape: a nested `metadata:` block the parser hoists
    "territories/home/lab/lab-backup-plan.md": (
        "---\nkind: territory\nname: lab-backup-plan\n"
        "description: \"SHIPPED 2026-08-24 — nightly backups, verified by hand.\"\n"
        "metadata: \n  node_type: memory\n  type: project\n"
        "  originSessionId: 00000000-0000-0000-0000-000000000000\n"
        "status: SHIPPED\nlast_verified: 2026-10-02\n---\n\n"
        "## Current\n\nNightly at 03:00.\n\n## History\n\nWeekly before that. "
        "See [[kit-sync-design]].\n"
    ),
    "territories/console/kit/MEMORY.md": (
        "---\nterritory: console/kit\nconsumes: home/lab\nconsumed_by: none\n---\n"
        "# console/kit\n\n## UPSTREAM CONTRACT\n\n"
        "- SSH to the lab box is READ-ONLY, never mutate state.\n\n## MEMORIES\n"
        "- [Sync design](kit-sync-design.md) — start here.\n"
        "- [Sync v1](kit-sync-v1.md) — the first cut.\n"
        "- [Fodder corpus](kit-fodder-corpus.md) — HISTORICAL.\n"
        "- [Gone file](kit-gone-file.md) — listed, but deleted.\n"
    ),
    # a version chain as direction §6 defines it: the older file stays SHIPPED and untouched, and
    # the hand-written index above still lists it -> superseded-still-indexed. (The store's
    # one real chain, cards/cairn, points at a file merged away before history began.)
    "territories/console/kit/kit-sync-design.md": (
        "---\nname: kit-sync-design\nkind: territory\nsupersedes: kit-sync-v1\n"
        "description: The current sync architecture; start here.\nstatus: IN FLIGHT\n"
        "last_verified: 2026-08-01\n---\n\nUses [[lab-ssh-read-only]] and [[kit-missing-note]].\n"
        "Template syntax [[ var ]] and prose [[override]] are not links.\n"
    ),
    "territories/console/kit/kit-sync-v1.md": (
        "---\nname: kit-sync-v1\nkind: territory\ndescription: The first sync cut.\n"
        "status: SHIPPED\n---\n\nSuperseded.\n"
    ),
    # tag-test-fodder-corpus.md's shape: a frontmatter line with no key at all, plus a
    # verify recipe whose directory is gone
    "territories/console/kit/kit-fodder-corpus.md": (
        "---\nname: kit-fodder-corpus\nkind: territory\n"
        "description: HISTORICAL test corpus.\nstatus: HISTORICAL\nvolatility: stable\n"
        "verify: test -d /nonexistent/fixture/corpus\n"
        "exit 1 as of 2026-09-15 — the directory is GONE. The measurements stand as recorded\n"
        "last_verified: 2024-09-15\n---\n\nMeasurements.\n"
    ),
    # underscore filename, no name: field -> fix renames it and inserts the name
    "territories/console/kit/kit_raw_notes.md": (
        "---\nkind: territory\ndescription: SHIPPED raw notes from the bench.\n---\n\nNotes.\n"
    ),
    "territories/console/kit/kit-unlisted-orphan.md": (
        "---\nname: kit-unlisted-orphan\nkind: territory\n"
        "description: Nothing links here and no router lists it.\nvolatility: live\n---\n\nAlone.\n"
    ),
    "territories/console/kit/kit-bad-recipe.md": (
        "---\nname: kit-bad-recipe\nkind: territory\ndescription: A recipe that pipes.\n"
        "verify: git log | head\nstatus: wat\nlast_verified: 2026-13-45\n---\n\n"
        "[[kit-sync-design]]\n"
    ),
    # archive/<group>/: a README.md with no frontmatter beside a retired memory, which is
    # how all six README-bearing groups in a real store's archive/ are laid out
    "archive/kit-old/README.md": (
        "# kit-old\n\nRetired with the old kit repo. "
        "Its nightly notes live on in kit-sync-design.\n"
    ),
    "archive/kit-old/kit-legacy-sync.md": (
        "---\nname: kit-legacy-sync\nkind: territory\ndescription: The retired nightly rsync job.\n"
        "status: HISTORICAL\n---\n\n## Nightly rsync\n\nRan at 02:00 until the kit moved.\n"
    ),
    # a legacy silo still holding content, one slug of which already lives in the store
    "projects/-Users-nobody-gone-repo/memory/MEMORY.md": (
        "# gone-repo\n- [Note](legacy-note.md)\n"
    ),
    "projects/-Users-nobody-gone-repo/memory/legacy-note.md": (
        "---\nname: legacy-note\n"
        "description: A legacy note about the lab box nightly backups verified.\n---\n\nOld.\n"
    ),
    "projects/-Users-nobody-gone-repo/memory/kit-sync-v1.md": (
        "---\nname: kit-sync-v1\ndescription: The first sync cut, legacy copy.\n---\n\nDup.\n"
    ),
}


@dataclass
class Fixture:
    home: Path
    store: Path
    projects: Path
    repo: Path       # a checkout whose silo is symlinked to console/kit
    elsewhere: Path  # a directory that maps to no territory

    def env(self, cwd: Path | None = None) -> dict[str, str]:
        e = dict(os.environ)
        e.update(HOME=str(self.home), CLAUDE_MEMORY_STORE=str(self.store),
                 CLAUDE_PROJECTS_DIR=str(self.projects),
                 CLAUDE_PROJECT_DIR=str(cwd or self.repo))
        e.pop("PYTHONPATH", None)
        return e


def build(base: Path, oversized: bool = False) -> Fixture:
    home = base / "home"
    store = home / ".claude" / "memory"
    projects = home / ".claude" / "projects"
    for rel, text in FILES.items():
        root = projects.parent if rel.startswith("projects/") else store
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (projects / "-Users-nobody-empty" / "memory").mkdir(parents=True)
    repo = (base / "work" / "kit.repo").resolve()
    (repo / ".git").mkdir(parents=True)
    (repo / "src").mkdir()
    elsewhere = (base / "work" / "elsewhere").resolve()
    elsewhere.mkdir(parents=True)
    silo = projects / silo_name(str(repo))
    silo.mkdir(parents=True)
    (silo / "memory").symlink_to(store / "territories" / "console" / "kit")
    if oversized:
        # Past MAX_CHARS (32,000): one huge standing directive, then a router big enough that
        # shortening every directive is not enough and trailing map sections must go too.
        big = "x " * 9000
        (store / "standing" / "huge-directive.md").write_text(
            "---\nname: huge-directive\nkind: standing\n"
            "description: The conclusion survives degradation.\n---\n\n" + big + "\n",
            encoding="utf-8")
        sections = "".join(f"## section {i:02d}\n- t/{i} : " + "y " * 1000 + "\n\n"
                           for i in range(20))
        (store / "ROUTER.md").write_text(FILES["ROUTER.md"] + "\n" + sections, encoding="utf-8")
    return Fixture(home, store, projects, repo, elsewhere)


@pytest.fixture(autouse=True)
def _no_outer_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as a pre-push hook, the suite inherits GIT_DIR and GIT_INDEX_FILE from the repo
    being pushed, and every fixture `git init` or commit would land in that repo instead."""
    from claude_hybrid_memory.storegit import REPO_ENV
    for k in REPO_ENV:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return build(tmp_path / "fx")


@pytest.fixture
def fx_oversized(tmp_path: Path) -> Fixture:
    return build(tmp_path / "oversized", oversized=True)


def run(cmd: list[str], env: dict[str, str], cwd: Path | None = None) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=60)
    return p.returncode, p.stdout, p.stderr


def mem_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "claude_hybrid_memory", *args]


def hook_cmd() -> list[str]:
    return mem_cmd("hook", "session-start")
