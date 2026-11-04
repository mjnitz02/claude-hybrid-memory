"""Legacy silos: resolving them to a working directory, and pointing them at a territory."""
from __future__ import annotations

import os
import re
from pathlib import Path

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.harness import encode, silo_name


def silo_workdir(silo: str) -> Path | None:
    """Reverse the harness's silo naming (claude_hybrid_memory.harness) by walking the real
    filesystem.

    The encoding is lossy -- `/`, `.`, `@`, `~`, `_`, a space and a literal `-` all become
    `-` -- so rather than guess at a joiner, encode what is actually on disk and compare,
    with runs of `-` collapsed on both sides. Greedy: prefer the longest run of tokens that
    matches a real directory. A silo an older harness named keeps its `_` (`Old_Vault`),
    so `_` in the silo name is folded to `-` before comparing.

    Returns None when the walk cannot be completed. That means only that nothing on THIS
    disk answers to the slug, which is not the same as the repo being dead: a repo parked
    on its remote resolves to None too. Callers must not read it as a death certificate.
    A name the harness truncated (past 200 characters, plus a hash) cannot be walked back
    and also returns None.
    """
    if not silo.startswith("-"):
        return None
    tokens = [t for t in silo.replace("_", "-").split("-") if t]
    if not tokens:
        return None
    cur = Path("/")
    i = 0
    while i < len(tokens):
        try:
            entries = [e for e in cur.iterdir() if e.is_dir()]
        except (PermissionError, OSError):
            return None
        keys = {re.sub(r"-+", "-", encode(e.name)).strip("-"): e for e in entries}
        matched = None
        for take in range(len(tokens) - i, 0, -1):
            hit = keys.get("-".join(tokens[i:i + take]))
            if hit is not None:
                matched = (hit, take)
                break
        if matched is None:
            return None
        cur, take = matched
        i += take
    return cur


def do_link(root: Path, legacy: Path, territory: str, target_dir: Path,
            write: bool) -> list[Finding]:
    """Point a repo's silo at a territory. Step 4 of the park/restore cycle.

    Parking a repo (pushing it to its remote and deleting the local checkout) leaves its
    memory behind in the store, which is the point. Restoring it later means re-pointing
    one silo, and the ritual -- work out the slug, mv the old dir aside, ln -s the
    territory -- is exactly the kind of thing that does not get remembered six weeks
    later. So it is a command.

    Refuses rather than guesses whenever the silo already holds real memory: that is a
    pending migration, not a re-link, and silently symlinking over it would strand files.
    """
    out: list[Finding] = []
    tpath = root / "territories" / territory
    if not (tpath / "MEMORY.md").is_file():
        out.append(Finding(ERROR, "link-no-territory", territory,
                           f"{tpath} has no MEMORY.md; create the territory first"))
        return out

    target_dir = target_dir.resolve()
    if not target_dir.is_dir():
        out.append(Finding(ERROR, "link-no-directory", str(target_dir),
                           "not a directory on this disk; clone the repo before linking"))
        return out

    silo = legacy / silo_name(str(target_dir))
    md = silo / "memory"

    # A link whose territory is gone (renamed, archived) holds nothing, so re-pointing it
    # strands nothing; only a link to a live territory needs a deliberate unlink.
    dangling = md.is_symlink() and not md.exists()
    if md.is_symlink() and not dangling:
        cur = Path(os.path.realpath(md))
        if cur == tpath.resolve():
            out.append(Finding(INFO, "link-already", silo.name, f"already -> {territory}"))
        else:
            out.append(Finding(WARN, "link-conflict", silo.name,
                               f"already points at {cur}; unlink it deliberately first"))
        return out

    if md.is_dir():
        files = [f for f in md.glob("*.md") if f.name != "MEMORY.md"]
        if files:
            out.append(Finding(ERROR, "link-silo-occupied", silo.name,
                               f"holds {len(files)} unmigrated memory file(s); run "
                               "the memory-migrate skill first -- linking over them would strand "
                               "knowledge in a directory nothing reads"))
            return out

    index = tpath / "MEMORY.md"
    name = target_dir.name
    listed = has_member(index.read_text(encoding="utf-8", errors="replace"), name)
    if not write:
        also = "" if listed else f", and add `{name}` to its members:"
        out.append(Finding(INFO, "link-would", silo.name,
                           f"would point {md} -> {tpath}{also} (rerun with --write)"))
        return out

    silo.mkdir(parents=True, exist_ok=True)
    if dangling:
        md.unlink()
    elif md.is_dir():
        md.rename(silo / "memory.premigration")
    md.symlink_to(tpath)
    out.append(Finding(INFO, "link-done", silo.name, f"-> {territory}"))
    if not listed:
        text = index.read_text(encoding="utf-8", errors="replace")
        new = with_member(text, name)
        if new is None:
            out.append(Finding(WARN, "link-members", str(index),
                               f"no frontmatter to add `{name}` to; add it to members: by hand"))
        else:
            index.write_text(new, encoding="utf-8")
            out.append(Finding(INFO, "link-members", str(index),
                               f"added `{name}: {NEW_MEMBER}` to members:; correct owner/mode "
                               "if this repo is not your own active work"))
    return out


# What a newly linked repo is recorded as. Linking is what a session does when it starts
# working in a repo, so active is the likely truth; owner is a guess the output names.
NEW_MEMBER = "{owner: self, mode: active}"


def _frontmatter_span(text: str) -> tuple[int, int] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    return (4, end + 1) if end != -1 else None


def has_member(text: str, name: str) -> bool:
    """Whether a territory MEMORY.md's `members:` already names this repo."""
    span = _frontmatter_span(text)
    if span is None:
        return False
    head = text[span[0]:span[1]]
    m = re.search(r"^members:[^\n]*\n((?:[ \t]+[^\n]*\n)*)", head, re.M)
    return bool(m and re.search(rf"^[ \t]+{re.escape(name)}\s*:", m.group(1), re.M))


def with_member(text: str, name: str) -> str | None:
    """The MEMORY.md with `name` added under `members:` (created if absent), as text so
    the hand-written flow style and comments survive. None without frontmatter. The link was
    the one writer of this relationship and never recorded it (eval 2026-11-04)."""
    span = _frontmatter_span(text)
    if span is None:
        return None
    a, b = span
    head = text[a:b]
    line = f"  {name}: {NEW_MEMBER}\n"
    m = re.search(r"^members:[ \t]*(\{\})?[ \t]*\n((?:[ \t]+[^\n]*\n)*)", head, re.M)
    if m:
        head = head[:m.start()] + "members:\n" + m.group(2) + line + head[m.end():]
    else:
        head = head + "members:\n" + line
    return text[:a] + head + text[b:]
