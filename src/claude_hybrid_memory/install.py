"""`mem install`: stand up or repair this machine's store, behind the plugin.

The scripted form of setup.md steps 1 to 3d. The `hybrid-memory` plugin carries the
hooks and skills (hooks/hooks.json, skills/); this does what a plugin cannot: create the
store, give it its own history, and write the rules file that imports the always-loaded
layer. Every step looks before it changes anything and can be re-run: what is already right
is reported and left alone, and a store file is never overwritten. Then it runs each hook
the way Claude Code will, against a copy of the store, so a broken hook shows up here and
not in every session. `--dry-run` reports what would change, writes nothing, and runs no hook.

Machines set up before the plugin (2026-11-03) carry the old wiring: `mem` hooks merged
into settings.json and one symlink per skill in ~/.claude/skills. With the plugin there too,
both would run twice, so once the plugin is present they are removed (settings.json backed
up first). Without the plugin they are left alone: removing them would leave no hooks.

`--dev` loads a checkout as the plugin by symlinking it into ~/.claude/skills, which Claude
Code loads as `hybrid-memory@skills-dir`, so edits are live. `make install` does that.

It writes one file outside the store, ~/.claude/rules/claude-hybrid-memory.md. Not done
here: editing MACHINE.md (only the user knows what is true of this box) or
~/.claude/CLAUDE.md (theirs; it is read, never written), territories and silo migration
(steps 4 and 5, which change where sessions read memory from).
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
from claude_hybrid_memory.hooks import session_start

REPO = Path(__file__).resolve().parents[2]
CLAUDE = session_start.CLAUDE_DIR
PLUGIN = "hybrid-memory"
MEM = REPO / "bin" / "mem"

DIRS = ("standing", "territories", "archive")
TEMPLATES = ("MACHINE.md", "GATES.md", "ROUTER.md", "RETRO.md")

# event -> (matcher, hook name): what hooks/hooks.json declares (tests/test_plugin.py holds
# the two together), and what the pre-plugin settings.json entries ran.
HOOKS = {
    "SessionStart": ("startup|resume|clear|compact", "session-start"),
    "PostToolUse": ("Read|Write|Edit|Bash", "post-tool"),
    "SessionEnd": (None, "session-end"),
}


def is_ours(hook: dict, name: str) -> bool:
    """A settings.json hook entry that runs `mem hook <name>`, in either the args or the
    one-string form, or the old `tools/session_start.py` it replaced."""
    if not isinstance(hook, dict):
        return False
    line = " ".join([str(hook.get("command", ""))] + [str(a) for a in hook.get("args") or []])
    if name == "session-start" and "tools/session_start.py" in line:
        return True
    words = line.split()
    return bool(words) and Path(words[0].strip('"')).name == "mem" and f"hook {name}" in line


def drop_hooks(settings: dict) -> list[str]:
    """Take every `mem` hook out of `settings["hooks"]` in place; returns what went. A group
    left empty goes with it, and an event left empty too. Any other hook stays, including
    one that shared a group with ours."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    gone = []
    for event, (_, name) in HOOKS.items():
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        n = 0
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                keep = [h for h in g["hooks"] if not is_ours(h, name)]
                n += len(g["hooks"]) - len(keep)
                g["hooks"] = keep
        if n:
            kept = [g for g in groups if not (isinstance(g, dict) and g.get("hooks") == [])]
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
            gone.append(f"{event}: removed `mem hook {name}`" + (f" x{n}" if n > 1 else ""))
    if not hooks:
        del settings["hooks"]
    return gone


def plugin_source(claude: Path) -> str | None:
    """Where this machine gets the plugin: a checkout in ~/.claude/skills (`skills-dir`), an
    install from a marketplace (`marketplace`), or nowhere. A session started with
    `--plugin-dir` cannot be seen from here."""
    manifest = claude / "skills" / PLUGIN / ".claude-plugin" / "plugin.json"
    try:
        if json.loads(manifest.read_text(encoding="utf-8")).get("name") == PLUGIN:
            return "skills-dir"
    except (OSError, ValueError, AttributeError):
        pass
    try:
        installed = json.loads((claude / "plugins" / "installed_plugins.json")
                               .read_text(encoding="utf-8")).get("plugins", {})
    except (OSError, ValueError, AttributeError):
        return None
    return "marketplace" if any(k.startswith(PLUGIN + "@") for k in installed) else None


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


def ensure_dev_link(repo: Path, claude: Path, dry: bool) -> list[Finding]:
    """`--dev`: symlink the checkout into ~/.claude/skills as the plugin itself."""
    dest = claude / "skills" / PLUGIN
    if dest.is_symlink() and Path(os.path.realpath(dest)) == repo.resolve():
        return [Finding(INFO, "install-ok", str(dest), f"loads this checkout ({repo})")]
    if dest.exists() and not dest.is_symlink():
        return [Finding(ERROR, "install-dev-link", str(dest),
                        f"exists and is not a symlink; left alone (wanted -> {repo})")]
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            dest.unlink()
        dest.symlink_to(repo.resolve())
    return [Finding(INFO, "install-dev-link", str(dest),
                    f"{'would link' if dry else 'linked'} -> {repo.resolve()}; loads as "
                    f"{PLUGIN}@skills-dir from the next session")]


def ensure_plugin(repo: Path, claude: Path, dry: bool, stamp: str,
                  source: str | None = None) -> list[Finding]:
    """The plugin must be there; once it is, the pre-plugin wiring must not be."""
    source = source or plugin_source(claude)
    if not source:
        return [Finding(WARN, "install-no-plugin", str(claude),
                        f"the {PLUGIN} plugin is not installed, so no hook runs and no skill "
                        "loads; see README (or `make install` for a dev checkout). Any "
                        "pre-plugin hooks and skill links are left in place until it is")]
    out = [Finding(INFO, "install-ok", str(claude), f"plugin present ({source})")]
    names = {p.parent.name for p in (repo / "skills").glob("*/SKILL.md")}
    skills = claude / "skills"
    for name in sorted(names):
        link = skills / name
        target = Path(os.path.realpath(link))
        if link.is_symlink() and target.parent.name == "skills" and (target / "SKILL.md").exists():
            if not dry:
                link.unlink()
            out.append(Finding(INFO, "install-legacy-skill", str(link),
                               f"{'would remove' if dry else 'removed'} pre-plugin link -> "
                               f"{target}; the plugin ships this skill"))
    path = claude / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError) as e:
        return out + [Finding(ERROR, "install-settings", str(path),
                              f"not readable JSON, untouched: {e}")]
    if not isinstance(settings, dict):
        return out + [Finding(ERROR, "install-settings", str(path), "unexpected shape, untouched")]
    gone = drop_hooks(settings)
    if gone and not dry:
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        backup.write_bytes(path.read_bytes())
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        gone.append(f"backup at {backup.name}")
    return out + [Finding(INFO, "install-legacy-hook", str(path),
                          ("would: " if dry else "") + g + ("" if g.startswith("backup") else
                                                            "; the plugin runs it now"))
                  for g in gone]


def ensure_rules(claude_md: Path, root: Path, dry: bool) -> list[Finding]:
    """Write the rules file that imports ALWAYS.md (setup.md step 3d). That import is the
    only way the layer reaches a session, since the hook's output is capped at 10,000 chars.
    `mem` owns the file, so a drifted one is rewritten. A CLAUDE.md that also imports the
    layer loads it twice; that is reported, and CLAUDE.md is never written."""
    rules = session_start.rules_path(claude_md)
    want = session_start.rules_text(root)
    out = []
    if session_start.read(rules) + "\n" == want:
        out.append(Finding(INFO, "install-ok", str(rules), "imports the always-loaded layer"))
    else:
        verb = "rewrite" if rules.exists() else "write"
        if not dry:
            rules.parent.mkdir(parents=True, exist_ok=True)
            tmp = rules.with_name(rules.name + ".tmp")
            tmp.write_text(want, encoding="utf-8")
            os.replace(tmp, rules)
        out.append(Finding(INFO, "install-rules", str(rules),
                           (f"would {verb}" if dry else f"{verb[:-1]}ten")
                           + ": imports the always-loaded layer"))
    if session_start.imports(root, claude_md):
        out.append(Finding(WARN, "install-imported-twice", str(claude_md),
                           f"also imports the layer, so it loads twice; delete the "
                           f"`{session_start.import_line(root)}` line (and its `# Memory` "
                           "block) from it"))
    return out


CHECK_SESSION = "mem-install-check"


def _hook(mem: str, name: str, payload: dict, env: dict) -> tuple[int, str, float]:
    t0 = time.perf_counter()
    try:
        p = subprocess.run([mem, "hook", name], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e), (time.perf_counter() - t0) * 1000
    return p.returncode, p.stdout, (time.perf_counter() - t0) * 1000


def check_hooks(root: Path, mem: str, repo: Path, claude: Path = CLAUDE) -> list[Finding]:
    """Run the three hooks as Claude Code will (setup.md, the checks under 3 to 3c),
    against a throwaway copy of the store, so nothing real is logged or committed.

    Every hook fails open, so an exit code alone proves little: each check looks for the
    effect instead. session-start hands over a non-empty context under the harness's
    persist threshold and renders ALWAYS.md; post-tool logs a read of
    a memory and stays silent; session-end commits a probe file left in the copy."""
    if not Path(mem).is_file():
        return [Finding(WARN, "install-check-skipped", mem, "no binary here; hooks not run")]
    out = []

    def bad(name: str, why: str) -> None:
        out.append(Finding(ERROR, f"install-check-{name}", mem, why))

    with tempfile.TemporaryDirectory(prefix="mem-install-check-") as tmp:
        copy = Path(tmp) / "memory"
        shutil.copytree(root, copy, symlinks=True, ignore=shutil.ignore_patterns(".cache"))
        env = {**os.environ, "CLAUDE_MEMORY_STORE": str(copy), "CLAUDE_PROJECT_DIR": str(repo),
               "CLAUDE_CONFIG_DIR": str(claude)}

        rc, so, ms = _hook(mem, "session-start", {"source": "startup"}, env)
        try:
            ctx = json.loads(so)["hookSpecificOutput"]["additionalContext"] if rc == 0 else ""
        except (ValueError, KeyError, TypeError):
            ctx = ""
        limit = session_start.HOOK_OUTPUT_LIMIT
        if ctx and len(ctx) > limit:
            bad("session-start", f"{len(ctx):,} chars of context, past the harness's "
                f"{limit:,}; sessions would see only a 2 KB preview of it")
        elif ctx and (copy / session_start.ALWAYS).is_file():
            out.append(Finding(INFO, "install-check-session-start", mem,
                               f"ok, {len(ctx):,} chars of context, ALWAYS.md rendered, "
                               f"{ms:.0f} ms"))
        elif ctx:
            bad("session-start", "no ALWAYS.md rendered; the rules file would import nothing")
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
        dry: bool = False, dev: bool = False) -> list[Finding]:
    now = dt.datetime.now()
    link = ensure_dev_link(repo, claude, dry) if dev else []
    # a dry run that would link the checkout counts it as present
    source = "skills-dir" if dev and dry else None
    out = (ensure_store(root, repo, dry)
           + ensure_git(root, dry, now.date().isoformat())
           + link
           + ensure_plugin(repo, claude, dry, now.strftime("%Y%m%d-%H%M%S"), source)
           + ensure_rules(claude / "CLAUDE.md", root, dry))
    if dry or any(f.level == ERROR for f in out):
        return out
    return out + check_hooks(root, str(mem), repo, claude)
