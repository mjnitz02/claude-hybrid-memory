"""Stage 2 (fast-adoption §5): one isolated headless Sonnet process per file, and one per silo.

Each process sees its directive, one input and nothing else that can be kept out (the
spike's measured floor is about 640 tokens of preamble, account email and environment),
so context never grows and no file can colour another's summary. Matt's call
(2026-10-23): headless `claude -p` driven from here, not subagents inside a session, for
robustness, reproducibility and control over how many run at once.

Summaries are cached by a key over model, directive, schema and input, so a re-run only
pays for what changed, and editing a directive re-summarizes everything it governs. No
summary passes through the calling session: they land in `.cache/migrate/summaries/`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from claude_hybrid_memory.migrate import AGENTS, workdir

MODEL = "sonnet"
JOBS = 4
TIMEOUT = 180
# The binary to run. Tests point this at a fake that answers from canned summaries.
RUNNER_ENV = "CLAUDE_MEMORY_SUMMARIZER"

# Everything the spike showed can be kept out of the process, is: no tools (the input
# arrives on stdin, so it can touch nothing and no PostToolUse event fires), no settings
# sources (keeps ~/.claude/CLAUDE.md out), no hooks (no router injected, no commit, no
# project directory left behind), no saved session.
ISOLATION = ["--tools", "", "--no-session-persistence", "--setting-sources", "",
             "--settings", '{"disableAllHooks": true}', "--output-format", "json"]


@dataclass
class Job:
    id: str
    kind: str          # "file" | "silo"
    input: str

    @property
    def directive(self) -> Path:
        return AGENTS / ("memory-summarizer.md" if self.kind == "file"
                         else "memory-silo-summarizer.md")

    @property
    def schema(self) -> Path:
        return AGENTS / ("memory-summary.schema.json" if self.kind == "file"
                         else "memory-silo-summary.schema.json")

    def key(self, model: str) -> str:
        h = hashlib.sha256()
        for part in (model, self.kind, self.directive.read_text(encoding="utf-8"),
                     self.schema.read_text(encoding="utf-8"), self.input):
            h.update(part.encode())
            h.update(b"\0")
        return h.hexdigest()


def file_input(f: dict, silo: dict) -> str:
    head = [f"silo: {f['silo']}", f"silo project: {silo.get('repo') or 'unknown'}",
            f"file: {f['file']}"]
    if f["index_line"]:
        head.append(f"index line: {f['index_line']}")
    raw = Path(f["path"]).read_text(encoding="utf-8", errors="replace")
    return "RECORD:\n" + "\n".join(head) + "\n\nFILE:\n" + raw


def silo_input(s: dict, files: list[dict], router: str) -> str:
    head = [f"silo: {s['silo']}", f"project: {s.get('repo') or 'unknown'}",
            "on this disk: " + (s["workdir"] or "no (not checked out here)"),
            f"memory files: {len(s['files'])}"]
    if s["index"].strip():
        body = s["index"]
    else:
        body = "(no index; the files and their descriptions)\n" + "\n".join(
            f"- {f['file']}: {f['meta'].get('description') or '(no description)'}"
            for f in files)
    return ("RECORD:\n" + "\n".join(head) + "\n\nFOLDER INDEX:\n" + body
            + "\n\nTERRITORY MAP:\n" + (router or "(no map yet)"))


def jobs_for(inv: dict, router: str, silos: list[str] | None = None) -> list[Job]:
    """Silo jobs first, so a partial run still has what the map is built from."""
    pick = [s for s in inv["silos"] if not silos or any(x in s["silo"] for x in silos)]
    names = {s["silo"] for s in pick}
    files = [f for f in inv["files"] if f["silo"] in names]
    by_silo = {s["silo"]: s for s in pick}
    out = [Job(s["silo"], "silo", silo_input(s, [f for f in files if f["silo"] == s["silo"]],
                                              router)) for s in pick]
    out += [Job(f["id"], "file", file_input(f, by_silo[f["silo"]])) for f in files]
    return out


def validate(obj, schema: dict, where: str = "$") -> list[str]:
    """The subset of JSON Schema the two schemas use: type, enum, required, properties,
    items, additionalProperties: false. Enough to refuse a malformed summary."""
    errs = []
    types = schema.get("type")
    if types is not None:
        types = types if isinstance(types, list) else [types]
        py = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
        if not any(isinstance(obj, py[t]) for t in types):
            return [f"{where}: expected {'/'.join(types)}"]
    if "enum" in schema and obj not in schema["enum"]:
        errs.append(f"{where}: {obj!r} not in {schema['enum']}")
    if isinstance(obj, dict):
        props = schema.get("properties", {})
        errs += [f"{where}: missing {k}" for k in schema.get("required", []) if k not in obj]
        if schema.get("additionalProperties") is False:
            errs += [f"{where}: unexpected {k}" for k in obj if k not in props]
        for k, sub in props.items():
            if k in obj:
                errs += validate(obj[k], sub, f"{where}.{k}")
    if isinstance(obj, list) and "items" in schema:
        for i, x in enumerate(obj):
            errs += validate(x, schema["items"], f"{where}[{i}]")
    return errs


def command(job: Job, model: str) -> list[str]:
    return [os.environ.get(RUNNER_ENV, "claude"), "-p", "--model", model, *ISOLATION,
            "--system-prompt-file", str(job.directive),
            "--json-schema", job.schema.read_text(encoding="utf-8")]


def _once(job: Job, model: str) -> dict:
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="mem-summarize-") as cwd:
        try:
            p = subprocess.run(command(job, model), input=job.input, capture_output=True,
                               text=True, cwd=cwd, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"status": "failed", "error": str(e)}
    ms = round((time.perf_counter() - t0) * 1000)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        return {"status": "failed", "ms": ms,
                "error": f"exit {p.returncode}: {(p.stderr or p.stdout).strip()[:300]}"}
    summary = out.get("structured_output")
    errs = (["no structured_output"] if summary is None
            else validate(summary, json.loads(job.schema.read_text(encoding="utf-8"))))
    u = out.get("usage") or {}
    rec = {"ms": ms, "cost_usd": out.get("total_cost_usd", 0.0),
           "model": next(iter(out.get("modelUsage") or {}), model),
           "tokens_in": sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                  "cache_read_input_tokens")),
           "tokens_out": u.get("output_tokens", 0)}
    if out.get("is_error") or errs:
        return {**rec, "status": "failed",
                "error": "; ".join(errs) or str(out.get("result", ""))[:300]}
    return {**rec, "status": "ok", "summary": summary}


def run_job(job: Job, model: str, cache: Path, force: bool = False) -> dict:
    """Summarize one job, from cache when the key matches. A failure is retried once and
    then cached as failed, so it shows in the map and is retried on the next run."""
    key = job.key(model)
    f = cache / f"{key}.json"
    if f.is_file() and not force:
        rec = json.loads(f.read_text(encoding="utf-8"))
        if rec.get("status") == "ok":
            return {**rec, "cached": True}
    rec = _once(job, model)
    if rec["status"] != "ok":
        rec = _once(job, model)
    rec = {"id": job.id, "kind": job.kind, "key": key, "requested_model": model,
           "at": dt.datetime.now().isoformat(timespec="seconds"), **rec}
    cache.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {**rec, "cached": False}


def run(root: Path, jobs: list[Job], model: str = MODEL, parallel: int = JOBS,
        force: bool = False, progress=None) -> list[dict]:
    cache = workdir(root) / "summaries"
    results = []
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futs = {pool.submit(run_job, j, model, cache, force): j for j in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            if progress:
                progress(n, len(jobs), r)
    order = {j.id: i for i, j in enumerate(jobs)}
    return sorted(results, key=lambda r: order[r["id"]])


def cached(root: Path, jobs: list[Job], model: str = MODEL) -> dict[str, dict]:
    """The summaries already on disk for `jobs`, by id; nothing is run."""
    cache = workdir(root) / "summaries"
    out = {}
    for j in jobs:
        f = cache / f"{j.key(model)}.json"
        if f.is_file():
            out[j.id] = json.loads(f.read_text(encoding="utf-8"))
    return out
