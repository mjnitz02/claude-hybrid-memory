"""The store's own git history (direction §16.1): the one place `mem` runs git, and only on the
store.

Matt's rule is that Claude touches git only when asked, in every repo. The store is the one
carve-out, written beside that rule in ~/.claude/CLAUDE.md: `mem` commits it on its own,
with generated messages, and never pushes, since the store has no remote. Every store git
operation goes through `mem`: `commit`, `log`, `diff`, `restore`, `show --at` and
`audit --at`. That keeps the carve-out narrow and easy to see: a session never runs `git`
against the store directly, and nothing here can reach another repository or a remote, or
rewrite history. A verb a session needs and `mem` lacks gets added here, not worked around.

The SessionEnd hook calls `commit` with no one asking, which is the point: history only
helps if it exists without anyone remembering to make it. A session that dies before its
SessionEnd leaves its changes for the next commit, whoever makes it.
"""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 20


@dataclass
class Result:
    status: str          # "committed" | "clean" | "skipped" | "failed"
    detail: str = ""     # the subject when committed, else why not
    sha: str = ""


def _git(root: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-C", str(root), *args], input=stdin, capture_output=True,
                          text=True, timeout=TIMEOUT, env=env)


def is_repo(root: Path) -> bool:
    """The store's OWN repository. A store sitting inside some other checkout is not one,
    and `git -C` would otherwise happily commit into the parent."""
    return (root / ".git").exists()


def area(path: str) -> str:
    """Where a store-relative path lives, for a commit subject: a territory, `standing`,
    an archive group, or the top-level file itself."""
    parts = path.split("/")
    if parts[0] == "territories" and len(parts) > 2:
        return "/".join(parts[1:-1])
    if parts[0] == "archive" and len(parts) > 2:
        return f"archive/{parts[1]}"
    return parts[0] if len(parts) > 1 else path


def message(changes: list[tuple[str, str]], added_lines: dict[str, int], trigger: str,
            session: str = "", subject: str | None = None) -> str:
    """A generated commit message: what changed where, then every path.

    `changes` is (status letter, path) from `git diff --cached --name-status`; `added_lines`
    maps a path to lines added, which for an events log is the number of new events."""
    events = [p for _, p in changes if p.startswith("events/")]
    files = [(s, p) for s, p in changes if not p.startswith("events/")]
    n_events = sum(added_lines.get(p, 0) for p in events)
    if subject is None:
        words = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed"}
        counts = dict.fromkeys(("added", "modified", "deleted", "renamed", "changed"), 0)
        for s, _ in files:
            w = words.get(s[0], "changed")
            counts[w] = counts.get(w, 0) + 1
        areas = list(dict.fromkeys(area(p) for _, p in files))
        where = ", ".join(areas[:3]) + (f" +{len(areas) - 3} more" if len(areas) > 3 else "")
        if files:
            subject = f"mem: {', '.join(f'{n} {w}' for w, n in counts.items() if n)} in {where}"
            if n_events:
                subject += f"; {n_events} events"
        else:
            subject = f"mem: {n_events} usage events"
    body = [f"Trigger: {trigger}" + (f" · session {session}" if session else "")]
    if events:
        body.append(f"Events: +{n_events} in {', '.join(events)}")
    if files:
        body.append("")
        body += [f"{s[0]}  {p}" for s, p in files]
    return subject + "\n\n" + "\n".join(body) + "\n"


def commit(root: Path, trigger: str, session: str = "", subject: str | None = None) -> Result:
    """Stage everything the store's .gitignore allows and commit it. Never pushes."""
    if not is_repo(root):
        return Result("skipped", f"{root} is not a git repository (setup.md step 1b)")
    if (root / ".git" / "index.lock").exists():
        return Result("skipped", "another git operation holds the store's index lock")
    try:
        add = _git(root, "add", "-A")
        if add.returncode:
            return Result("failed", add.stderr.strip())
        names = _git(root, "diff", "--cached", "--name-status", "-z").stdout.split("\0")
        changes, i = [], 0
        while i < len(names) - 1:
            s = names[i]
            # a rename or copy carries two paths, old then new; name the new one
            i += 3 if s[:1] in "RC" else 2
            changes.append((s, names[i - 1]))
        if not changes:
            return Result("clean", "nothing to commit")
        added = {}
        for ln in _git(root, "diff", "--cached", "--numstat").stdout.splitlines():
            a, _, p = ln.split("\t", 2)
            added[p] = int(a) if a.isdigit() else 0
        msg = message(changes, added, trigger, session, subject)
        c = _git(root, "commit", "-q", "-F", "-", stdin=msg)
        if c.returncode:
            return Result("failed", (c.stderr or c.stdout).strip())
        sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
        return Result("committed", msg.split("\n", 1)[0], sha)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Result("failed", str(e))


def passthrough(root: Path, *args: str) -> int:
    """Run a read-only git command on the store with its output going straight through."""
    return subprocess.run(["git", "--no-pager", "-C", str(root), *args], timeout=60).returncode


def file_log(root: Path, path: str) -> list[list[str]] | None:
    """One file's history across renames, newest first, as [date, short sha, subject];
    None when there is no history to read."""
    try:
        r = _git(root, "log", "--follow", "--date=short", "--format=%ad%x09%h%x09%s", "--", path)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [ln.split("\t", 2) for ln in r.stdout.splitlines()] if r.returncode == 0 else None


def changed_files(root: Path, since: str | None = None) -> str | None:
    """`git log --name-only`, one NUL before each commit's paths; None on failure."""
    args = ["log", "--name-only", "--format=%x00"] + ([f"--since={since}"] if since else [])
    try:
        r = _git(root, *args)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def pending(root: Path) -> list[str]:
    """What the next commit would take: changed and untracked paths, store-relative."""
    r = _git(root, "status", "--porcelain", "--untracked-files=all")
    return [ln[3:] for ln in r.stdout.splitlines()]


def untracked(root: Path, paths: list[str]) -> list[str]:
    r = _git(root, "ls-files", "--others", "--exclude-standard", "--", *paths)
    return r.stdout.splitlines()


def resolve(root: Path, rev: str) -> str | None:
    """The full sha `rev` names in the store's history, or None."""
    r = _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return r.stdout.strip() if r.returncode == 0 else None


def read_at(root: Path, rev: str, path: str) -> bytes | None:
    """A store-relative file as it was at `rev`, or None if it did not exist there."""
    r = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{path}"], capture_output=True,
                       timeout=TIMEOUT)
    return r.stdout if r.returncode == 0 else None


def locate(root: Path, rev: str, path: str) -> str:
    """`path` as `rev` knows it: store-relative, else under territories/, the way a
    territory is named everywhere else (`console/tools/MEMORY.md`)."""
    if not files_at(root, rev, [path]) and files_at(root, rev, [f"territories/{path}"]):
        return f"territories/{path}"
    return path


def files_at(root: Path, rev: str, paths: list[str]) -> list[str]:
    """The files `paths` (files or directories) covered at `rev`."""
    r = _git(root, "ls-tree", "-r", "-z", "--name-only", rev, "--", *paths)
    return [x for x in r.stdout.split("\0") if x]


@dataclass
class Restore:
    status: str                      # "restored" | "failed"
    detail: str = ""
    changed: list[str] | None = None
    unchanged: list[str] | None = None
    snapshot: str = ""               # the safety commit taken first, if there was anything


def restore(root: Path, paths: list[str], rev: str = "HEAD") -> Restore:
    """Put `paths` back as they were at `rev`. Never deletes: a file added since is left
    alone, and a path `rev` lacks fails the whole call before anything is written.

    It commits the store first, so whatever is overwritten stays in history; the restore
    itself is an ordinary change for the next commit."""
    if not is_repo(root):
        return Restore("failed", f"{root} is not a git repository (setup.md step 1b)")
    sha = resolve(root, rev)
    if not sha:
        return Restore("failed", f"{rev!r} names no commit in the store")
    outside = [p for p in paths if p.startswith("..") or os.path.isabs(p)]
    if outside:
        return Restore("failed", f"outside the store: {', '.join(outside)}")
    files, missing = [], []
    for p in paths:
        got = files_at(root, sha, [locate(root, sha, p)])
        files += got
        if not got:
            missing.append(p)
    if missing:
        return Restore("failed", f"not in {rev}: {', '.join(missing)}")
    snap = commit(root, f"before mem restore from {rev}")
    if snap.status not in ("committed", "clean"):
        return Restore("failed", f"safety commit {snap.status}: {snap.detail}")
    changed, unchanged = [], []
    for f in dict.fromkeys(files):
        data = read_at(root, sha, f)
        dest = root / f
        if dest.is_file() and dest.read_bytes() == data:
            unchanged.append(f)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        changed.append(f)
    return Restore("restored", rev, changed, unchanged, snap.sha)


def export(root: Path, rev: str, dest: Path) -> None:
    """Write the store's tree at `rev` into `dest`, outside the store; no checkout, no
    worktree, nothing in .git touched."""
    r = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", rev],
                       capture_output=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace").strip())
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(dest, filter="data")


GITIGNORE = """\
.cache/
.DS_Store

# Claude Code's relevant-memories recall index (2.1.306, flag-gated, dormant 2026-10-21).
# Written into whichever memory dir it indexes, i.e. a territory. Derived; never commit.
.bm25-index.json
"""


def ignore_missing(root: Path) -> list[str]:
    """The GITIGNORE patterns the store's .gitignore lacks."""
    f = root / ".gitignore"
    have = set(f.read_text(encoding="utf-8").splitlines()) if f.is_file() else set()
    return [ln for ln in GITIGNORE.splitlines() if ln and not ln.startswith("#") and ln not in have]


def ensure_ignore(root: Path) -> list[str]:
    """Write GITIGNORE, or append the patterns an existing .gitignore lacks. Returns them."""
    f = root / ".gitignore"
    missing = ignore_missing(root)
    if not f.is_file():
        f.write_text(GITIGNORE, encoding="utf-8")
    elif missing:
        text = f.read_text(encoding="utf-8")
        f.write_text(text + ("" if text.endswith("\n") else "\n") + "\n".join(missing) + "\n",
                     encoding="utf-8")
    return missing


def enclosing(root: Path) -> str | None:
    """The checkout `root` sits inside, when it has no .git of its own; None if none."""
    r = _git(root, "rev-parse", "--show-toplevel")
    return r.stdout.strip() if r.returncode == 0 and not is_repo(root) else None


def init(root: Path, today: str) -> Result:
    """Give the store its own history (setup.md step 1b): `git init`, the .gitignore, and
    a baseline commit. Refuses a store inside another checkout, so nothing is ever committed
    into a parent repository. A store that already has its .git is left alone."""
    if is_repo(root):
        return Result("skipped", "already a git repository")
    try:
        top = enclosing(root)
        if top:
            return Result("failed", f"{root} sits inside the checkout {top}; refusing to nest")
        i = _git(root, "init", "-q")
        if i.returncode:
            return Result("failed", i.stderr.strip())
        ensure_ignore(root)
        add = _git(root, "add", "-A")
        if add.returncode:
            return Result("failed", add.stderr.strip())
        subject = f"Baseline: store as of {today}, set up by mem install"
        c = _git(root, "commit", "-q", "--allow-empty", "-m", subject)
        if c.returncode:
            return Result("failed", "initialized, but the baseline commit failed: "
                          + (c.stderr or c.stdout).strip())
        sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
        return Result("committed", subject, sha)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Result("failed", str(e))


def revert(root: Path, shas: list[str]) -> Result:
    """Undo commits by adding their inverse, newest first: history is kept, never rewritten.
    On a conflict nothing is left half-done: the revert is aborted and reported."""
    if not is_repo(root):
        return Result("failed", f"{root} is not a git repository (setup.md step 1b)")
    snap = commit(root, "before mem revert")
    if snap.status not in ("committed", "clean"):
        return Result("failed", f"safety commit {snap.status}: {snap.detail}")
    r = _git(root, "revert", "--no-edit", *shas)
    if r.returncode:
        _git(root, "revert", "--abort")
        return Result("failed", (r.stderr or r.stdout).strip())
    return Result("committed", f"reverted {len(shas)} commit(s)",
                  _git(root, "rev-parse", "--short", "HEAD").stdout.strip())


def subjects(root: Path) -> list[tuple[str, str]]:
    """(short sha, subject) of every store commit, newest first."""
    r = _git(root, "log", "--format=%h%x09%s")
    return [tuple(ln.split("\t", 1)) for ln in r.stdout.splitlines() if "\t" in ln] \
        if r.returncode == 0 else []
