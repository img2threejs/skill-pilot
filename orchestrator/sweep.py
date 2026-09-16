#!/usr/bin/env python3
"""Find and kill what agent runs leave behind — without touching anything live.

    sweep.py              # report only
    sweep.py --kill       # kill what it reports

A server spawned by `npm test` in one worktree once survived 15 hours holding the exact port the
suite computes for the next run. The next agent waited on that bind for 1h44m, burning 10 seconds
of CPU, and looked exactly like a hung model. This finds that class of thing before it costs
another round.

Three categories are never touched:

  * **container processes** — a parent of `containerd-shim` means this is PID 1 of a running
    container, not an orphan. Killing production because its parent looked odd is a real risk:
    it was attempted once and only the kernel's permission check prevented it.
  * **children of a live agent** — walk up the parent chain; if it reaches a running `pi` or
    `pilot.py`, the process is that run's work.
  * **anything outside this host's workspaces** — editor servers, the harness's own plugins.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

KILL = "--kill" in sys.argv
WORKSPACES = "/home/team/workspaces"
AGENT_PATTERNS = (re.compile(r"\bpi -p\b"), re.compile(r"pilot\.py\b"))
# What an agent run leaves behind: servers it started, test runners, bundlers.
LEFTOVER = re.compile(r"(dist-server/server\.mjs|procedural-server\.mjs|tests/run\.mjs"
                      r"|node_modules/\.bin/vite|--test-coverage|esbuild)")


def ps_all() -> list[dict]:
    out = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,etimes=,pcpu=,comm=,args="],
        capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, etimes, pcpu, comm, args = parts
        rows.append({"pid": int(pid), "ppid": int(ppid), "etimes": int(etimes),
                     "cpu": float(pcpu), "comm": comm, "args": args})
    return rows


rows = ps_all()
by_pid = {r["pid"]: r for r in rows}
live_agents = {r["pid"] for r in rows if any(p.search(r["args"]) for p in AGENT_PATTERNS)}


def ancestry(pid: int) -> list[dict]:
    """Walk up to init, so a process can be attributed to whatever started it."""
    chain, seen = [], set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        row = by_pid.get(pid)
        if not row:
            break
        chain.append(row)
        pid = row["ppid"]
    return chain


def verdict(row: dict) -> tuple[str, str]:
    chain = ancestry(row["pid"])
    if any(c["comm"].startswith("containerd-shim") or c["comm"] == "dockerd" for c in chain):
        return "keep", "inside a container"
    if any(c["pid"] in live_agents for c in chain[1:]):
        return "keep", "child of a live agent"
    if row["pid"] in live_agents:
        return "keep", "is a live agent"
    parent = by_pid.get(row["ppid"])
    if parent is None or row["ppid"] == 1:
        return "orphan", f"reparented to init, {row['etimes'] // 60}m old"
    return "orphan", f"parent {parent['comm']} is not an agent, {row['etimes'] // 60}m old"


candidates = [r for r in rows
              if LEFTOVER.search(r["args"]) and (WORKSPACES in r["args"] or r["comm"] in ("node", "esbuild"))]

orphans, kept = [], []
for row in candidates:
    kind, why = verdict(row)
    (orphans if kind == "orphan" else kept).append((row, why))

print(f"live agents: {sorted(live_agents) or 'none'}")
for row, why in kept:
    print(f"  keep    pid={row['pid']:<8} {why:<28} {row['args'][:60]}")
if not orphans:
    print("no leftovers")
    sys.exit(0)

for row, why in orphans:
    print(f"  ORPHAN  pid={row['pid']:<8} {why:<28} {row['args'][:60]}")

if not KILL:
    print(f"\n{len(orphans)} leftover(s). Re-run with --kill to end them.")
    sys.exit(1)

for row, _ in orphans:
    try:
        os.kill(row["pid"], 15)
    except ProcessLookupError:
        pass
import time
time.sleep(3)
for row, _ in orphans:
    try:
        os.kill(row["pid"], 0)
        os.kill(row["pid"], 9)
        print(f"  killed pid={row['pid']} (needed SIGKILL)")
    except (ProcessLookupError, PermissionError):
        print(f"  killed pid={row['pid']}")
