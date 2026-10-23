"""Secret scan over everything the store commits, plus the legacy silos.

The store is under git now, and memories about infrastructure are exactly where a pasted
token ends up. A finding never prints the matched value:
audit output lands in transcripts, which would leak exactly what this exists to catch.
"""
from __future__ import annotations

import re
from pathlib import Path

from claude_hybrid_memory.findings import ERROR, WARN, Finding
from claude_hybrid_memory.store import Memory

# Specific formats: a match is a credential until shown otherwise.
SPECIFIC = {
    "aws-access-key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github-token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})",
    "anthropic-key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "openai-key": r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}",
    "slack-token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "google-api-key": r"\bAIza[0-9A-Za-z_-]{35}",
    "private-key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "jwt": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
}
SPECIFIC_RE = [(k, re.compile(v)) for k, v in SPECIFIC.items()]

# `name = value` where the value looks like a literal token: 16+ chars of a token alphabet,
# both letters and digits. On the real store (2026-10-21) the looser form only ever hit
# code (`secret = xx_xxx[:0x10]`), which the alphabet excludes.
ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)"
    r"\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9+/=_.\-]{16,})(?![\w\[(])")


def check_secrets(root: Path, legacy_mems: list[Memory]) -> list[Finding]:
    files = [p for p in sorted(root.rglob("*.md"))
             if not {".git", ".cache"} & set(p.relative_to(root).parts)]
    texts = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in files]
    texts += [(m.path, m.raw) for m in legacy_mems]
    out = []
    for p, text in texts:
        for n, line in enumerate(text.split("\n"), 1):
            for kind, rx in SPECIFIC_RE:
                for m in rx.finditer(line):
                    out.append(Finding(ERROR, "secret", str(p),
                                       f"line {n}: looks like a {kind} ({len(m.group(0))} chars). "
                                       "Rotate it if real, then remove it from the file and "
                                       "from git history."))
            for m in ASSIGN_RE.finditer(line):
                v = m.group(2)
                if re.search(r"[A-Za-z]", v) and re.search(r"\d", v):
                    out.append(Finding(WARN, "secret-maybe", str(p),
                                       f"line {n}: `{m.group(1)}` assigned a token-like value "
                                       f"({len(v)} chars). Check it is not a live credential."))
    return out
