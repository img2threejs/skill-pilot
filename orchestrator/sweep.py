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
DISK = "--disk" in sys.argv
WORKSPACES = "/home/team/workspaces"
AGENT_PATTERNS = (re.compile(r"\bpi -p\b"), re.compile(r"pilot\.py\b"))
# What an agent run leaves behind: servers it started, test runners, bundlers.
LEFTOVER = re.compile(r"(dist-server/server\.mjs|procedural-server\.mjs|tests/run\.mjs"
                      r"|node_modules/\.bin/vite|--test-coverage|esbuild)")


def alive(pid: int) -> bool:
    """One correct liveness check, so nobody writes another wrong one.

    `ps -eo pid -p <pid>` prints every process on the host: `-e` overrides `-p`. That form has
    twice answered "everything is alive" to a question about one dead process, once inside a
    monitor that then reported a finished agent as running for 56 minutes.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else


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


def disk_report(reclaim: bool = False) -> None:
    """Anonymous Docker volumes, and how close the host is to falling over.

    `docker run postgres:18` without `-v` creates an anonymous volume and nothing removes it.
    Four hundred and thirty-five of them were deleted one morning; by the afternoon there were
    488 holding 23 GB, the disk hit 100%, Docker killed every container — the deployment included
    — and an agent died mid-round with ENOSPC. The disk filling is not a tidiness problem; it is
    an outage that arrives disguised as an unrelated failure.
    """
    free = subprocess.run(["df", "--output=pcent,avail", "-h", "/"],
                          capture_output=True, text=True).stdout.splitlines()
    used = free[1].split()[0] if len(free) > 1 else "?"
    avail = free[1].split()[1] if len(free) > 1 else "?"
    anon = subprocess.run(
        ["bash", "-c", "docker volume ls -q | grep -cE '^[0-9a-f]{64}$' || true"],
        capture_output=True, text=True).stdout.strip() or "0"
    in_use = subprocess.run(
        ["bash", "-c", "docker ps -q | xargs -I{} docker inspect {} "
         "--format '{{range .Mounts}}{{if eq .Type \"volume\"}}{{.Name}} {{end}}{{end}}' "
         "2>/dev/null | tr ' ' '\\n' | grep -cE '^[0-9a-f]{64}$' || true"],
        capture_output=True, text=True).stdout.strip() or "0"
    print(f"disk {used} used, {avail} free | {anon} anonymous volume(s), {in_use} in use")
    if int(anon) and not int(in_use) and reclaim:
        subprocess.run(["bash", "-c",
                        "docker volume ls -q | grep -E '^[0-9a-f]{64}$' | xargs -r -n50 docker volume rm"],
                       capture_output=True)
        print("  reclaimed — none of them was attached to a running container")
    elif int(anon) and not reclaim:
        print("  pass --disk with --kill to reclaim them")


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

if DISK:
    disk_report(KILL)
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
