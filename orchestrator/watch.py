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


def look(worktree: str, previous: dict) -> dict:
    pid = agent_pid(worktree)
    commits = len(git(worktree, "log", "--oneline", "origin/staging..HEAD").splitlines())
    dirty = [line[3:].strip() for line in git(worktree, "status", "--porcelain").splitlines()
             if line[3:].strip()]
    transcript = log_path(worktree)
    size = transcript.stat().st_size if transcript and transcript.exists() else 0
    newest = newest_mtime([str(Path(worktree) / f) for f in dirty]) if dirty else None
    idle = round(time.time() - newest) if newest else None

    if pid is None:
        verdict = "DONE" if commits and not dirty else "FAILED"
        detail = (f"{commits} commit(s), clean" if verdict == "DONE"
                  else f"{commits} commit(s), {len(dirty)} file(s) left uncommitted")
    else:
        moved = size > previous.get("size", 0) or (idle is not None and idle < 120)
        if moved:
            verdict, detail = "WORKING", f"{commits} commit(s), log {size // 1024}KB"
        elif idle is not None and idle > STALL_SECONDS:
            verdict, detail = "STALLED", f"nothing edited for {idle // 60}m, log flat"
        else:
            verdict, detail = "WORKING", f"{commits} commit(s), quiet but recent"
    return {"verdict": verdict, "detail": detail, "size": size, "pid": pid}


def main() -> int:
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
