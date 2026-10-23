"""Migration state of the legacy silos."""
from __future__ import annotations

import os
from pathlib import Path

from claude_hybrid_memory.findings import ERROR, INFO, WARN, Finding
from claude_hybrid_memory.silos import silo_workdir


def check_silos(legacy_root: Path, store_root: Path) -> list[Finding]:
    """Migration state, plus silos whose working directory is gone."""
    out = []
    if not legacy_root.is_dir():
        return out
    store_slugs: dict[str, str] = {}
    tdir = store_root / "territories"
    if tdir.is_dir():
        for f in tdir.rglob("*.md"):
            if f.name in ("MEMORY.md", "EXPORTS.md"):
                continue
            store_slugs[f.stem] = str(f.parent.relative_to(tdir))
    for silo in sorted(legacy_root.iterdir()):
        md = silo / "memory"
        if md.is_symlink() and not (md / "MEMORY.md").is_file():
            # exists() follows the link, so a territory renamed or archived out from under
            # this silo would otherwise vanish from the audit without a word
            fix = ("repoint it with `mem link`" if not md.exists() else
                   "the target still exists, so remove the link by hand, then `mem link`")
            out.append(Finding(ERROR, "silo-dangling", silo.name,
                               f"-> {os.readlink(md)}, which is not a territory; the "
                               f"repo loads no memory. {fix}"))
            continue
        if not md.exists():
            continue
        if md.is_symlink():
            out.append(Finding(INFO, "silo-migrated", silo.name,
                               f"-> {os.readlink(md)}"))
            continue
        files = [f for f in md.glob("*.md") if f.name != "MEMORY.md"]
        if not files:
            continue
        wd = silo_workdir(silo.name)
        if wd is None:
            out.append(Finding(WARN, "silo-not-checked-out", silo.name,
                               f"{len(files)} memory files but no directory on disk resolves "
                               "to this silo; decide archive vs `mode: parked` -- absence from "
                               "THIS disk is not evidence the repo is dead"))
        collide = sorted({f.stem for f in files} & set(store_slugs))
        if collide:
            out.append(Finding(ERROR, "silo-mixed-state", silo.name,
                               f"still holds {len(collide)} slug(s) that also live in the store: "
                               + ", ".join(collide[:5])))
        else:
            out.append(Finding(INFO, "silo-pending", silo.name,
                               f"{len(files)} files, not yet reviewed"))
    return out
