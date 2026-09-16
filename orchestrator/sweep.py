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
# An agent is identified by its process NAME, not by the arguments it was launched with.
# PI execs node and node then sets its process title to `pi` — one word, no path, no
# flags — so a pattern like `pi -p` matches the launch command and never a running agent.
# Measured: with a live PI working in pg-15 and two wedged ones 4 and 5 days old, this
# script reported "live agents: none" and "no leftovers". A sweep that cannot see a live
# agent is one --kill away from killing the work it was written to protect.
AGENT_COMMS = frozenset({"pi", "dsh"})
AGENT_PATTERNS = (re.compile(r"pilot\.py\b"),)
# An agent that has spent almost no CPU over a long life is not working, it is wedged —
# the documented `pi -p` stdin hang burns 0.94 seconds in 8h50m. Flagged, never killed
# without --kill, and only past MIN_WEDGED_AGE so a starting agent is never mistaken for
# a stuck one.
MIN_WEDGED_AGE = 2 * 3600
WEDGED_CPU_RATIO = 0.005
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


def end(pid: int) -> None:
    """SIGTERM, then SIGKILL if it is still there.

    A wedged PI does not answer SIGTERM: both four-day-old ones measured here survived it
    and needed SIGKILL. A sweep that sends TERM and reports success leaves them running.
    """
    import time as _time
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        print(f"  ended pid={pid}")
        return
    _time.sleep(3)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        print(f"  ended pid={pid}")
        return
    try:
        os.kill(pid, 9)
        print(f"  ended pid={pid} (needed SIGKILL)")
    except ProcessLookupError:
        print(f"  ended pid={pid}")


def ps_all() -> list[dict]:
    out = subprocess.run(
        # `cputimes` is total CPU seconds consumed. It is what separates an agent that is
        # working from one that is merely alive; `pcpu` is an average over the process's
        # whole life and reads as ~0 for both.
        ["ps", "-eo", "pid=,ppid=,etimes=,cputimes=,pcpu=,comm=,args="],
        capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        pid, ppid, etimes, cputimes, pcpu, comm, args = parts
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = ""          # gone, or owned by another user — not a reason to guess
        rows.append({"pid": int(pid), "ppid": int(ppid), "etimes": int(etimes),
                     "cputimes": int(cputimes), "cpu": float(pcpu), "comm": comm,
                     "args": args, "cwd": cwd})
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
    # Reclaim whenever there is anything to reclaim. The earlier condition also required
    # in_use == 0, which is never true on a host running containers — so on the only host
    # this script exists for, it never reclaimed anything, and the disk filled twice while
    # the report said how to fix it. `docker volume rm` refuses a volume that is attached,
    # so the in-use ones are protected by Docker rather than by declining to run.
    if int(anon) and reclaim:
        subprocess.run(["bash", "-c",
                        "docker volume ls -q | grep -E '^[0-9a-f]{64}$' | xargs -r -n50 docker volume rm"],
                       capture_output=True)
        after = subprocess.run(["bash", "-c",
                                "docker volume ls -q | grep -cE '^[0-9a-f]{64}$' || true"],
                               capture_output=True, text=True).stdout.strip() or "0"
        print(f"  reclaimed {int(anon) - int(after)}; {after} left (attached, refused by docker)")
    elif int(anon) and not reclaim:
        print("  pass --disk with --kill to reclaim them")


# Containers the test suite starts and does not always remove. Names come from the test
# FILE, not the worktree — `pg14-` is admissionLedger.test.ts — so a running agent's tests
# create containers with the same prefixes as an abandoned run's. Prefix is therefore not a
# safe discriminator; age plus an idle connection count is. Measured: 18 leaked postgres
# containers aged 2 to 3.5 hours, alongside four live ones under 12 minutes old.
TEST_CONTAINER = re.compile(r"^(pg\d+[a-z]*|pg\d+own)-")
# Never touch these, whatever their age. `playground-job-results-db` is postgres:18 exactly
# like the test containers, so filtering on the image alone would have taken the production
# database down; an earlier draft of this filter also matched `playground-app`.
PROTECTED_CONTAINER = re.compile(r"^(playground-|traefik$)")
MIN_CONTAINER_AGE = 3600


def container_report(reclaim: bool = False) -> None:
    listed = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.CreatedAt}}"],
        capture_output=True, text=True).stdout
    stale = []
    for line in listed.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[1] != "postgres:18":
            continue
        name = parts[0]
        if PROTECTED_CONTAINER.search(name) or not TEST_CONTAINER.search(name):
            continue
        started = subprocess.run(
            ["docker", "inspect", name, "--format", "{{.State.StartedAt}}"],
            capture_output=True, text=True).stdout.strip()
        age = subprocess.run(["date", "-d", started, "+%s"], capture_output=True, text=True).stdout.strip()
        if not age or time.time() - int(age) < MIN_CONTAINER_AGE:
            continue
        # A container with a live client backend belongs to a run in progress, however old
        # it looks. Postgres counts its own background workers in pg_stat_activity, so the
        # backend_type filter is what makes this a count of clients rather than of eight.
        env = subprocess.run(["docker", "inspect", name, "--format",
                              "{{range .Config.Env}}{{println .}}{{end}}"],
                             capture_output=True, text=True).stdout
        password = next((l.split("=", 1)[1] for l in env.splitlines()
                         if l.startswith("POSTGRES_PASSWORD=")), "")
        clients = subprocess.run(
            ["docker", "exec", "-e", f"PGPASSWORD={password}", name, "psql", "-U", "postgres", "-tAc",
             "select count(*) from pg_stat_activity "
             "where backend_type='client backend' and pid<>pg_backend_pid()"],
            capture_output=True, text=True).stdout.strip()
        if clients != "0":
            continue      # busy, or the probe failed — either way, not ours to remove
        stale.append((name, int((time.time() - int(age)) // 60)))

    if not stale:
        print("no stale test containers")
        return
    for name, minutes in stale:
        print(f"  STALE   {name:<24} {minutes}m old, 0 client backends")
    if not reclaim:
        print(f"  {len(stale)} stale test container(s). --kill removes them.")
        return
    subprocess.run(["docker", "rm", "-f", *[n for n, _ in stale]], capture_output=True)
    print(f"  removed {len(stale)} stale test container(s)")


rows = ps_all()
by_pid = {r["pid"]: r for r in rows}
live_agents = {r["pid"] for r in rows
               if r["comm"] in AGENT_COMMS or any(p.search(r["args"]) for p in AGENT_PATTERNS)}


def wedged(row: dict) -> str | None:
    """An agent process that is alive but has done nothing for a long time."""
    if row["comm"] not in AGENT_COMMS or row["etimes"] < MIN_WEDGED_AGE:
        return None
    if row["cputimes"] > row["etimes"] * WEDGED_CPU_RATIO:
        return None
    return (f"{row['cputimes']}s CPU in {row['etimes'] // 3600}h — wedged, "
            f"cwd={row['cwd'] or '?'}")


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
    container_report(KILL)
print(f"live agents: {sorted(live_agents) or 'none'}")

stuck = [(r, why) for r in rows if (why := wedged(r))]
for row, why in stuck:
    print(f"  WEDGED  pid={row['pid']:<8} {why}")
if stuck and not KILL:
    print(f"  {len(stuck)} wedged agent(s) hold memory and a model session. --kill ends them.")
if stuck and KILL:
    for row, _ in stuck:
        end(row["pid"])
    print(f"  ended {len(stuck)} wedged agent(s)")
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
