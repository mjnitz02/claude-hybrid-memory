"""Findings and the report every command prints."""
from __future__ import annotations

import json
from dataclasses import dataclass

ERROR, WARN, INFO = "error", "warn", "info"

ORDER = {ERROR: 0, WARN: 1, INFO: 2}
SHOW_PER_CODE = 6


@dataclass
class Finding:
    level: str
    code: str
    path: str
    message: str


def report(findings: list[Finding], as_json: bool) -> int:
    if as_json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        findings = sorted(findings, key=lambda f: (ORDER[f.level], f.code, f.path))
        counts = {ERROR: 0, WARN: 0, INFO: 0}
        for f in findings:
            counts[f.level] += 1
        by_code: dict[tuple[str, str], list[Finding]] = {}
        for f in findings:
            by_code.setdefault((f.level, f.code), []).append(f)
        for (level, code), group in by_code.items():
            n = len(group)
            print(f"\n[{level.upper()}] {code}" + (f"  x{n}" if n > 1 else ""))
            for f in group[:SHOW_PER_CODE]:
                print(f"  {f.path}\n      {f.message}")
            if n > SHOW_PER_CODE:
                print(f"  ... and {n - SHOW_PER_CODE} more (use --json for all)")
        print(f"\n{counts[ERROR]} error, {counts[WARN]} warn, {counts[INFO]} info")
    return 1 if any(f.level == ERROR for f in findings) else 0
