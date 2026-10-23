"""`mem install`: stand up or repair this machine's store and wire Claude Code to it.

The scripted form of setup.md steps 1 to 3c; `make install` runs it after installing the
`mem` tool itself. Every step looks before it changes anything and can be re-run: what is
already right is reported and left alone, a file is never overwritten, and settings.json
is backed up before it is rewritten. Then it runs each hook the way Claude Code will,
against a copy of the store, so a broken hook shows up here and not in every session.
`--dry-run` reports what would change, writes nothing, and runs no hook.

Not done here: editing MACHINE.md (only Matt knows what is true of this box) or
~/.claude/CLAUDE.md (his instructions; it is checked, never written), territories and silo
migration (steps 4 and 5, which change where sessions read memory from).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from claude_hybrid_memory import storegit
from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding

REPO = Path(__file__).resolve().parents[2]
CLAUDE = Path.home() / ".claude"
MEM = Path.home() / ".local" / "bin" / "mem"

DIRS = ("standing", "territories", "archive")
TEMPLATES = ("MACHINE.md", "GATES.md", "ROUTER.md", "RETRO.md")

# event -> (matcher, hook name, extra fields): setup.md steps 3, 3b and 3c, which say why
HOOKS = {
    "SessionStart": ("startup|resume|clear|compact", "session-start",
                     {"statusMessage": "Loading memory router"}),
    "PostToolUse": ("Read|Write|Edit|Bash", "post-tool", {}),
    "SessionEnd": (None, "session-end", {}),
}


def hook_group(event: str, mem: str) -> dict:
    """The settings.json group for one event, exactly as setup.md shows it."""
    matcher, name, extra = HOOKS[event]
    hook = {"type": "command", "command": mem, "args": ["hook", name], "timeout": 10, **extra}
    return ({"matcher": matcher} if matcher else {}) | {"hooks": [hook]}


def is_ours(hook: dict, name: str) -> bool:
    """A hook entry that runs `mem hook <name>`, in either the args or the one-string form,
    or the old `tools/session_start.py` it replaced."""
    if not isinstance(hook, dict):
        return False
    line = " ".join([str(hook.get("command", ""))] + [str(a) for a in hook.get("args") or []])
    if name == "session-start" and "tools/session_start.py" in line:
        return True
    words = line.split()
    return bool(words) and Path(words[0]).name == "mem" and f"hook {name}" in line


def merge_hooks(settings: dict, mem: str) -> list[str]:
    """Bring `settings["hooks"]` to the wanted state in place; returns what changed.

    Only `mem` entries are touched. Unless exactly one is there and already right, every
    one is taken out (a group left empty goes with it) and the wanted group goes where the
    first was, so a hook sharing a group with ours keeps its matcher, and a second copy,
    which would run twice, is gone."""
    hooks = settings.setdefault("hooks", {})
    changes = []
    for event, (_, name, _) in HOOKS.items():
        want = hook_group(event, mem)
        groups = hooks.setdefault(event, [])
        found = [(i, g, h) for i, g in enumerate(groups) for h in g.get("hooks", [])
                 if is_ours(h, name)]
        if len(found) == 1 and found[0][1] == want:
            continue
        for _, g, h in found:
            g["hooks"].remove(h)
        at = found[0][0] if found else len(groups)
        kept = [g for g in groups[:at] if g.get("hooks")]
        hooks[event] = kept + [want] + [g for g in groups[at:] if g.get("hooks")]
        verb = "updated" if found else "added"
        extra = f" ({len(found) - 1} duplicate removed)" if len(found) > 1 else ""
        changes.append(f"{event}: {verb} `mem hook {name}`{extra}")
    return changes


def ensure_store(root: Path, repo: Path, dry: bool) -> list[Finding]:
    out = []
    made = [d for d in DIRS if not (root / d).is_dir()]
    if made:
        if not dry:
            for d in made:
                (root / d).mkdir(parents=True, exist_ok=True)
        out.append(Finding(INFO, "install-store", str(root),
                           ("would create " if dry else "created ") + ", ".join(made)))
    for t in TEMPLATES:
        dest = root / t
        if dest.exists():
            continue
        if not dry:
            dest.write_bytes((repo / "templates" / t).read_bytes())
        out.append(Finding(INFO, "install-template", str(dest),
                           ("would copy " if dry else "copied ") + f"templates/{t}"))
        if t == "MACHINE.md":
            out.append(Finding(WARN, "install-edit-machine", str(dest),
                               "fill in the machine name and this box's calibration "
                               "(setup.md step 1)"))
    if not out:
        out.append(Finding(INFO, "install-ok", str(root), "store directories and files present"))
    return out


def ensure_git(root: Path, dry: bool, today: str) -> list[Finding]:
    if storegit.is_repo(root):
        missing = storegit.ignore_missing(root)
        if not missing:
            return [Finding(INFO, "install-ok", str(root / ".git"), "store has its own history")]
        if not dry:
            storegit.ensure_ignore(root)
        return [Finding(INFO, "install-gitignore", str(root / ".gitignore"),
                        ("would add " if dry else "added ") + ", ".join(missing))]
    top = storegit.enclosing(root) if root.is_dir() else None
    if top:
        return [Finding(ERROR, "install-git", str(root),
                        f"sits inside the checkout {top}; refusing to nest a repository")]
    if dry:
        return [Finding(INFO, "install-git", str(root),
                        "would `git init` the store and make a baseline commit")]
    r = storegit.init(root, today)
    if r.status == "committed":
        return [Finding(INFO, "install-git", str(root), f"initialized; {r.sha} {r.detail}")]
    return [Finding(ERROR, "install-git", str(root), r.detail)]


def ensure_skills(repo: Path, skills: Path, dry: bool) -> list[Finding]:
    """Symlink each repo skill into Claude Code's skills dir (setup.md step 2)."""
    out = []
    for src in sorted(p.parent for p in (repo / "skills").glob("*/SKILL.md")):
        dest = skills / src.name
        if dest.is_symlink():
            if Path(os.path.realpath(dest)) == src.resolve():
                continue
            verb = "relink"
        elif dest.exists():
            out.append(Finding(WARN, "install-skill", str(dest),
                               f"exists and is not a symlink; left alone (wanted -> {src})"))
            continue
        else:
            verb = "link"
        if not dry:
            skills.mkdir(parents=True, exist_ok=True)
            if dest.is_symlink():
                dest.unlink()
            dest.symlink_to(src)
        out.append(Finding(INFO, "install-skill", str(dest),
                           f"{'would ' + verb if dry else verb + 'ed'} -> {src}"))
    return out or [Finding(INFO, "install-ok", str(skills), "skills linked")]


def ensure_settings(path: Path, mem: str, dry: bool, stamp: str) -> list[Finding]:
    """Merge the three hooks into settings.json (setup.md steps 3 to 3c)."""
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError) as e:
        return [Finding(ERROR, "install-settings", str(path),
                        f"not readable JSON, untouched: {e}")]
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        return [Finding(ERROR, "install-settings", str(path), "unexpected shape, untouched")]
    changes = merge_hooks(settings, mem)
    out = []
    if not Path(mem).is_file():
        out.append(Finding(WARN, "install-mem-missing", mem,
                           "the hooks point here but nothing is installed; run `make install`"))
    if not changes:
        return out + [Finding(INFO, "install-ok", str(path), "memory hooks current")]
    if not dry:
        if path.exists():
            backup = path.with_name(f"{path.name}.bak-{stamp}")
            backup.write_bytes(path.read_bytes())
            changes.append(f"backup at {backup.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    return out + [Finding(INFO, "install-hook", str(path), ("would: " if dry else "") + c)
                  for c in changes]


def ensure_exception(claude_md: Path, repo: Path) -> list[Finding]:
    """~/.claude/CLAUDE.md must carry the store's git carve-out beside the git rule it
    narrows (direction §16.1), so no session reads the rule without it. Checked, never written."""
    text = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
    for para in text.split("\n\n"):
        low = para.lower()
        if ".claude/memory" in low and "commit" in low and ("exception" in low
                                                            or "carve-out" in low):
            return [Finding(INFO, "install-ok", str(claude_md), "store git exception present")]
    return [Finding(WARN, "install-git-exception", str(claude_md),
                    "no exception for the store's own commits; add "
                    f"{repo / 'templates' / 'CLAUDE-git-exception.md'} under the git rule")]


CHECK_SESSION = "mem-install-check"


def _hook(mem: str, name: str, payload: dict, env: dict) -> tuple[int, str, float]:
    t0 = time.perf_counter()
    try:
        p = subprocess.run([mem, "hook", name], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e), (time.perf_counter() - t0) * 1000
    return p.returncode, p.stdout, (time.perf_counter() - t0) * 1000


def check_hooks(root: Path, mem: str, repo: Path) -> list[Finding]:
    """Run the three hooks as Claude Code will (setup.md, the checks under 3 to 3c),
    against a throwaway copy of the store, so nothing real is logged or committed.

    Every hook fails open, so an exit code alone proves little: each check looks for the
    effect instead. session-start hands over a non-empty context; post-tool logs a read of
    a memory and stays silent; session-end commits a probe file left in the copy."""
    if not Path(mem).is_file():
        return [Finding(WARN, "install-check-skipped", mem, "no binary here; hooks not run")]
    out = []

    def bad(name: str, why: str) -> None:
        out.append(Finding(ERROR, f"install-check-{name}", mem, why))

    with tempfile.TemporaryDirectory(prefix="mem-install-check-") as tmp:
        copy = Path(tmp) / "memory"
        shutil.copytree(root, copy, symlinks=True, ignore=shutil.ignore_patterns(".cache"))
        env = {**os.environ, "CLAUDE_MEMORY_STORE": str(copy), "CLAUDE_PROJECT_DIR": str(repo)}

        rc, so, ms = _hook(mem, "session-start", {"source": "startup"}, env)
        try:
            ctx = json.loads(so)["hookSpecificOutput"]["additionalContext"] if rc == 0 else ""
        except (ValueError, KeyError, TypeError):
            ctx = ""
        if ctx:
            out.append(Finding(INFO, "install-check-session-start", mem,
                               f"ok, {len(ctx):,} chars of context, {ms:.0f} ms"))
        else:
            bad("session-start", f"exit {rc}, no context; every session would start without "
                "the router. Try `mem hook session-start` by hand")

        target = next(iter(sorted((copy / "standing").glob("*.md"))), copy / "ROUTER.md")
        read = {"tool_name": "Read", "tool_input": {"file_path": str(target)},
                "session_id": CHECK_SESSION, "cwd": str(repo)}
        rc, so, ms = _hook(mem, "post-tool", read, env)
        logged = any(CHECK_SESSION in f.read_text(encoding="utf-8")
                     for f in (copy / "events").glob("*.jsonl"))
        if rc == 0 and not so and logged:
            out.append(Finding(INFO, "install-check-post-tool", mem,
                               f"ok, a memory read logged, {ms:.0f} ms"))
        else:
            bad("post-tool", f"exit {rc}, output {so[:80]!r}, read logged: {logged}")

        # a change for the hook to commit, so "clean afterwards" means it committed something
        (copy / f"{CHECK_SESSION}.md").write_text("probe\n", encoding="utf-8")
        rc, so, ms = _hook(mem, "session-end", {"reason": "other", "session_id": CHECK_SESSION},
                           env)
        left = storegit.pending(copy) if storegit.is_repo(copy) else ["(no .git)"]
        if rc == 0 and not left:
            out.append(Finding(INFO, "install-check-session-end", mem,
                               f"ok, a change committed, {ms:.0f} ms"))
        else:
            bad("session-end", f"exit {rc}, still uncommitted: {', '.join(left[:5])}")
    return out


def run(root: Path, repo: Path = REPO, claude: Path = CLAUDE, mem: Path = MEM,
        dry: bool = False) -> list[Finding]:
    now = dt.datetime.now()
    out = (ensure_store(root, repo, dry)
           + ensure_git(root, dry, now.date().isoformat())
           + ensure_skills(repo, claude / "skills", dry)
           + ensure_settings(claude / "settings.json", str(mem), dry,
                             now.strftime("%Y%m%d-%H%M%S"))
           + ensure_exception(claude / "CLAUDE.md", repo))
    if dry or any(f.level == ERROR for f in out):
        return out
    return out + check_hooks(root, str(mem), repo)
