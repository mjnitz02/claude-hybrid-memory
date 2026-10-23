"""Freshness, and the constrained execution of `verify:` recipes."""
from __future__ import annotations

import datetime as dt
import subprocess

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.spec import STALE_AFTER
from claude_hybrid_memory.store import Memory

VERIFY_ALLOW = {"git", "gh", "uv", "task", "ls", "test"}
VERIFY_DENY = {
    "push", "merge", "reset", "checkout", "rebase", "commit", "rm", "clean",
    "delete", "close", "create", "edit", "switch", "restore", "mv", "add",
}
SHELL_META = set("|&;><$`(){}\n\\")
VERIFY_TIMEOUT = 20


def validate_recipe(cmd: str) -> tuple[list[str] | None, str | None]:
    s = cmd.strip()
    if not s:
        return None, "empty"
    bad = sorted(set(s) & SHELL_META)
    if bad:
        return None, "contains shell metacharacters: " + " ".join(repr(c) for c in bad)
    argv = s.split()
    if argv[0] not in VERIFY_ALLOW:
        return None, f"leading command {argv[0]!r} not in allowlist {sorted(VERIFY_ALLOW)}"
    for tok in argv[1:]:
        if tok.lstrip("-").lower() in VERIFY_DENY:
            return None, f"mutating subcommand {tok!r} is denied"
    return argv, None


def age_phrase(age: int | None) -> str:
    return "never verified" if age is None else f"{age}d since last_verified"


def check_freshness(mems: list[Memory], today: dt.date, run: bool) -> list[Finding]:
    out = []
    for m in mems:
        vol = m.volatility or "slow"
        limit = STALE_AFTER.get(vol, 90)
        age = m.age_days(today)
        recipe = str(m.meta.get("verify") or "").strip()
        due = age is None or age > limit
        if recipe:
            argv, err = validate_recipe(recipe)
            if err:
                out.append(Finding(ERROR, "verify-refused", str(m.path), f"verify: {err}"))
                continue
            if not (run and due):
                if due:
                    out.append(Finding(INFO, "verify-due", str(m.path),
                                       f"{vol}; {age_phrase(age)}; recipe validates, pass --run "
                                       "to execute"))
                continue
            try:
                pr = subprocess.run(argv, capture_output=True, text=True, timeout=VERIFY_TIMEOUT)
                got = (pr.stdout or pr.returncode and pr.stderr or "").strip().splitlines()
                got = got[0] if got else ""
                exp = str(m.meta.get("expect") or "").strip()
                if pr.returncode != 0:
                    out.append(Finding(WARN, "verify-failed", str(m.path),
                                       f"exit {pr.returncode}: {(pr.stderr or '').strip()[:160]}"))
                elif exp and exp not in got:
                    out.append(Finding(ERROR, "verify-contradicted", str(m.path),
                                       f"expected {exp!r}, got {got[:120]!r}"))
                else:
                    out.append(Finding(INFO, "verify-confirmed", str(m.path),
                                       f"confirmed: {got[:120]!r}"))
            except subprocess.TimeoutExpired:
                out.append(Finding(WARN, "verify-timeout", str(m.path),
                                   f"exceeded {VERIFY_TIMEOUT}s"))
            except FileNotFoundError:
                out.append(Finding(WARN, "verify-unrunnable", str(m.path),
                                   f"{argv[0]} not on PATH"))
        elif due and vol == "live":
            out.append(Finding(WARN, "stale-live", str(m.path),
                               f"live, {age_phrase(age)}, and carries no verify: recipe"))
        elif due:
            out.append(Finding(INFO, "stale", str(m.path),
                               f"{vol}; {age_phrase(age)} (limit {limit}d)"))
    return out
