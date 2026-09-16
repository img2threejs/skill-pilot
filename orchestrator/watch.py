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

import json
import os
import subprocess
import sys

import progress
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
    """PI's own session transcript for this worktree — the file it writes as it works.

    Three wrong answers preceded this one. First the glob `/tmp/claude-*/**/scratchpad/<n>*.log`
    matched by bare number prefix and reported a DIFFERENT run's day-old 6MB file as pg-11's
    progress, while two other worktrees matched nothing and printed `log 0KB` — an absence
    dressed as a measurement. Then pilot.py's own capture turned out to hold 111 bytes for a
    whole run: PI writes nothing to stdout, so that file is not a progress signal either.

    PI keeps a JSONL transcript per working directory under ~/.pi/agent/sessions/, and it grows
    on every model turn — including the reading-and-verifying turns that touch no file at all,
    which is exactly when the other signals go quiet and the agent looks stalled. Measured:
    1.8MB over 425 lines for a run whose worktree had not been written to in 89 minutes.
    """
    # PI's encoding, measured rather than guessed: `/home/team/workspaces/pg-15` becomes
    # `--home-team-workspaces-pg-15--`. Leading slash contributes the first dash, and the name
    # is closed with two. Getting this wrong fails silently — the directory simply is not there
    # and the transcript reads as 0KB, which is the same wrong answer this function has already
    # given twice under different causes.
    slug = "-" + str(Path(worktree).resolve()).replace("/", "-") + "--"
    directory = Path.home() / ".pi/agent/sessions" / slug
    sessions = sorted(directory.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    return sessions[0] if sessions else None


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
        # The transcript's mtime is when PI last appended a turn, and it needs no baseline —
        # `size > previous` is trivially true on the first poll, so every worktree read WORKING
        # the first time it was looked at, whatever its real state.
        turn_idle = round(time.time() - transcript.stat().st_mtime) if transcript else None
        moved = (turn_idle is not None and turn_idle < 180) or (idle is not None and idle < 120)
        if moved:
            # Alive is not the same as getting somewhere. An agent repeating one failing
            # command appends a transcript turn every few seconds and reads as WORKING forever;
            # pg-15 did exactly that for eighty minutes. progress.verdict reads what the turns
            # actually contain.
            made, why = progress.verdict(transcript, produced_recently=bool(idle and idle < 600)) \
                if transcript else ("UNKNOWN", "no transcript")
            if made in ("LOOPING", "GRINDING"):
                verdict, detail = made, f"{commits} commit(s), {why}"
            else:
                when = f"last turn {turn_idle}s ago" if turn_idle is not None else "no transcript"
                verdict, detail = "WORKING", f"{commits} commit(s), {when}, {why}"
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
        needs_attention = [w for w in args
                           if state[w]["verdict"] in ("STALLED", "FAILED", "LOOPING", "GRINDING")]
        if needs_attention:
            print(f"  ATTENTION: {', '.join(Path(w).name for w in needs_attention)}")
        if not interval or all(state[w]["pid"] is None for w in args):
            return 1 if needs_attention else 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
