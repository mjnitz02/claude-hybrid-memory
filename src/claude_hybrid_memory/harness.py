"""Claude Code's own naming of a project directory under ~/.claude/projects/.

Taken from the 2.1.306 binary, not inferred from directory listings (an earlier empirical
reading kept `_`, which only an older harness did):

    function k(e){return e.replace(/[^a-zA-Z0-9]/g,"-")}
    function D0(e){let n=k(e);if(n.length<=200)return n;
                   return `${n.slice(0,200)}-${Math.abs(Jce(e)).toString(36)}`}

Imported by the SessionStart hook, so stdlib only and nothing heavy.
"""
from __future__ import annotations

import re

MAX_LEN = 200


def _units(s: str) -> list[int]:
    """UTF-16 code units, which is what a JS string is made of."""
    b = s.encode("utf-16-le", "surrogatepass")
    return [int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)]


def encode(s: str) -> str:
    """`k`: every non-alphanumeric UTF-16 unit becomes `-`, so an astral character is two."""
    return re.sub(r"[^A-Za-z0-9]", lambda m: "-" * (2 if ord(m.group()) > 0xFFFF else 1), s)


def _hash36(s: str) -> str:
    """`Jce` then base 36: Java's String.hashCode over UTF-16 units, as a signed int32."""
    h = 0
    for u in _units(s):
        h = (h * 31 + u) & 0xFFFFFFFF
    n = abs(h - (1 << 32) if h & 0x80000000 else h)
    digits = ""
    while True:
        n, r = divmod(n, 36)
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + digits
        if n == 0:
            return digits


def silo_name(path: str) -> str:
    """`D0`: the directory name the harness reads memory from for `path`."""
    n = encode(path)
    return n if len(n) <= MAX_LEN else f"{n[:MAX_LEN]}-{_hash36(path)}"
