#!/usr/bin/env python3
"""Poll every dispatched agent and say which ones need attention.

Fire-and-forget cost this project hours. An agent that dies without committing, one wedged on a
command that never returns, one that ended cleanly an hour ago — all three look identical from the
outside, which is silence. The orchestrator then discovers the state only when someone asks.

    watch.py <worktree> [<worktree> …]            # one report
    watch.py --loop 120 <worktree> [<worktree> …] # poll until every agent is done

Each worktree gets one of four verdicts:

    WORKING   alive, and something moved since the last look
    STALLED   alive, but the log is flat and nothing it edits has been touched for a long while
    DONE      no agent, and commits landed with a clean tree
    FAILED    no agent, and nothing landed — or work is stranded uncommitted
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from probe import agent_pid, newest_mtime, run  # noqa: E402

STALL_SECONDS = 900


def git(worktree: str, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=worktree, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return ""


def log_path(worktree: str) -> Path | None:
    """The transcript a dispatch wrote for this worktree, if the convention was followed."""
    name = Path(worktree).name.replace("pg-", "")
    for candidate in Path("/tmp").glob(f"claude-*/**/scratchpad/{name}*.log"):
        return candidate
    return None


def descendant_cpu(pid: int) -> tuple[int, float]:
    """Total CPU seconds burned by the agent's descendants, and the age of the youngest.

    Having a child is not the same as working. Measured: pg-15 sat 81 minutes with a live
    child shell whose own child was a `node -e` holding `setInterval` and ignoring SIGTERM —
    the agent had written `kill -TERM $PID; wait $PID` against a process whose handler only
    logs and never exits, so `wait` could never return. The child existed, used zero CPU, and
    an earlier version of this check called that WORKING for 81 minutes.

    CPU that is still climbing is work. A child that just appeared has not had time to burn
    any, so its age is reported too and the caller treats a fresh one as work.
    """
    stack, total, youngest = [pid], 0, float("inf")
    seen: set[int] = set()
    ticks = os.sysconf("SC_CLK_TCK")
    try:
        uptime = float(open("/proc/uptime").read().split()[0])
    except OSError:
        uptime = 0.0
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            with open(f"/proc/{current}/task/{current}/children") as fh:
                stack.extend(int(x) for x in fh.read().split())
        except (OSError, ValueError):
            continue
        if current == pid:
            continue
        try:
            fields = open(f"/proc/{current}/stat").read().rsplit(") ", 1)[1].split()
        except (OSError, IndexError):
            continue
        total += (int(fields[11]) + int(fields[12])) // ticks      # utime + stime
        youngest = min(youngest, uptime - int(fields[19]) / ticks)  # starttime
    return total, youngest


def look(worktree: str, previous: dict) -> dict:
    pid = agent_pid(worktree)
    commits = len(git(worktree, "log", "--oneline", "origin/staging..HEAD").splitlines())
    dirty = [line[3:].strip() for line in git(worktree, "status", "--porcelain").splitlines()
             if line[3:].strip()]
    transcript = log_path(worktree)
    size = transcript.stat().st_size if transcript and transcript.exists() else 0
    newest = newest_mtime([str(Path(worktree) / f) for f in dirty]) if dirty else None
    idle = round(time.time() - newest) if newest else None

    # An agent running a command is working, even when nothing it edits has moved and its log
    # is flat. Measured: pg-15 sat 38 minutes without touching a file while a child shell ran a
    # grep and a SIGTERM probe, and this function called it STALLED. Verification is mostly
    # reading and running, not writing, so file mtime alone cries wolf on exactly the agents
    # being most careful — and a false STALLED is what leads to killing work in progress.
    child_cpu, youngest_child = descendant_cpu(pid) if pid else (0, float("inf"))
    # Work is CPU that is still climbing, or a child too young to have burned any yet. A child
    # sitting at a flat CPU total across a whole poll is not evidence of anything.
    busy = youngest_child < 120 or child_cpu > previous.get("child_cpu", -1)

    if pid is None:
        verdict = "DONE" if commits and not dirty else "FAILED"
        detail = (f"{commits} commit(s), clean" if verdict == "DONE"
                  else f"{commits} commit(s), {len(dirty)} file(s) left uncommitted")
    else:
        moved = size > previous.get("size", 0) or (idle is not None and idle < 120)
        if moved:
            verdict, detail = "WORKING", f"{commits} commit(s), log {size // 1024}KB"
        elif busy:
            verdict = "WORKING"
            detail = (f"{commits} commit(s), running a command"
                      f"{f', nothing edited for {idle // 60}m' if idle else ''}")
        elif youngest_child < float("inf"):
            verdict = "STALLED"
            detail = (f"{commits} commit(s), child alive but 0 CPU for a full poll"
                      f"{f', nothing edited for {idle // 60}m' if idle else ''}")
        elif idle is not None and idle > STALL_SECONDS:
            verdict, detail = "STALLED", f"nothing edited for {idle // 60}m, log flat, no child running"
        else:
            verdict, detail = "WORKING", f"{commits} commit(s), quiet but recent"
    return {"verdict": verdict, "detail": detail, "size": size, "pid": pid,
            "child_cpu": child_cpu}


def main() -> int:
    # A watcher redirected to a file is the normal case, and Python block-buffers stdout
    # there: one run reported nothing at all for twenty minutes while the agent it watched
    # was working, because 4KB of rows had not yet filled a buffer. A poller that cannot be
    # read while it polls is the failure it exists to prevent.
    sys.stdout.reconfigure(line_buffering=True)

    args = sys.argv[1:]
    interval = 0
    if args and args[0] == "--loop":
        interval, args = int(args[1]), args[2:]
    if not args:
        print(__doc__)
        return 2

    state: dict[str, dict] = {w: {} for w in args}
    while True:
        rows = []
        for worktree in args:
            state[worktree] = look(worktree, state[worktree])
            s = state[worktree]
            rows.append(f"  {Path(worktree).name:<12} {s['verdict']:<8} {s['detail']}")
        print(f"[{time.strftime('%H:%M:%S')}]")
        print("\n".join(rows))
        needs_attention = [w for w in args if state[w]["verdict"] in ("STALLED", "FAILED")]
        if needs_attention:
            print(f"  ATTENTION: {', '.join(Path(w).name for w in needs_attention)}")
        if not interval or all(state[w]["pid"] is None for w in args):
            return 1 if needs_attention else 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
