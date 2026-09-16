#!/usr/bin/env python3
"""The measurements that keep being got wrong, written once.

Nine rules in CHECKLIST.md have been broken twice or more, and almost every one of them is a
shell idiom retyped by hand: `$?` read after a pipe (three times), `ps -e` beside `-p` (twice),
`pkill -f` matching the caller's own command line (twice), an unanchored grep matching text
*about* a thing (twice). Writing the correct incantation into a document did not stop the wrong
one being typed the next time — the rule was recorded and then broken by the very next tool
written after it.

So these stop being prose. Import them, or run this file:

    probe.py alive <pid>
    probe.py run '<command>'            # real exit status, never a pipe's
    probe.py footer <repo> <rev-range>  # anchored; a commit body may *mention* a trailer
    probe.py stalled <worktree> <log>   # three signals, not one
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path


def alive(pid: int) -> bool:
    """Does this pid exist?

    NOT `ps -eo pid -p <pid>`: `-e` overrides `-p`, so that prints every process on the host. It
    has twice answered "everything is alive" about one dead process, once inside a monitor that
    then reported a finished agent as running for 56 minutes.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


SWALLOWS_STATUS = re.compile(r"\|\s*(tail|head|grep|cut|awk|sed|wc|sort|uniq|jq|python3?)\b")


def run(command: str, cwd: str | None = None, timeout: int = 1800,
        allow_pipe: bool = False) -> tuple[int, str, str]:
    """Run a command and return its own exit status.

    `cmd | tail -3; echo $?` reports `tail`, not `cmd` — a false `exit=0` for a run that exited
    124, three times now. Documenting that did not stop it being retyped, so this refuses the
    shape instead: a trailing filter raises unless `allow_pipe=True` says the status genuinely
    does not matter. Capture the output here and slice it in Python.
    """
    if not allow_pipe and SWALLOWS_STATUS.search(command):
        raise ValueError(
            f"this command pipes into a filter, so its exit status would be the filter's, "
            f"not the command's: {command!r}. Drop the pipe and slice the returned output, "
            f"or pass allow_pipe=True if the status truly does not matter."
        )
    done = subprocess.run(["bash", "-lc", command], cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)
    return done.returncode, done.stdout, done.stderr


FOOTER = re.compile(r"^(Co-Authored-By:|🤖 Generated with)", re.M)


def footer_count(repo: str, rev_range: str) -> int:
    """Count real AI attribution trailers in a commit range.

    Anchored at line start on purpose. An unanchored search for "co-authored" matched a commit
    body that *said* "no Co-Authored-By trailer", and a clean commit was amended for a violation
    that never existed. A check for a thing must not match text about the thing.
    """
    code, out, _ = run(f"git log --format=%B {rev_range}", cwd=repo)
    return 0 if code != 0 else len(FOOTER.findall(out))


def newest_mtime(paths: list[str]) -> float | None:
    stamps = [Path(p).stat().st_mtime for p in paths if Path(p).exists()]
    return max(stamps) if stamps else None


def agent_pid(worktree: str) -> int | None:
    """The agent process working in this worktree.

    Ask the kernel where a process actually is — `/proc/<pid>/cwd` — rather than guessing from
    its arguments. Three earlier versions of this got it wrong in three different ways: matching
    `comm == "pi"` returned whatever stray run was oldest on the host; matching the worktree in
    argv missed every agent launched with `cd <worktree> && pi …`, because the path is the cwd and
    never appears in argv; and matching loosely returned the caller's own shell. The cwd is the
    one thing that cannot be confused with a mention of the path.
    """
    root = Path(worktree).resolve()
    out = subprocess.run(["ps", "-eo", "pid=,comm=,args="], capture_output=True, text=True).stdout
    candidates = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, comm, args = int(parts[0]), parts[1], parts[2]
        if comm != "pi" and "pilot.py" not in args:
            continue
        # Two harnesses name their target two ways. `pilot.py` takes `--cwd <worktree>` and runs
        # from wherever it was launched; `pi` is launched by `cd <worktree> && pi …`, so the path
        # is its cwd and never appears in argv. Check both, or half the agents look absent.
        if f"--cwd {root}" in args or f"--cwd {worktree}" in args:
            candidates.append((pid, comm))
            continue
        # A process that names its target explicitly is not working on any other worktree, even
        # though it runs from one.
        if "--cwd " in args:
            continue
        try:
            if Path(f"/proc/{pid}/cwd").resolve() == root:
                candidates.append((pid, comm))
        except (OSError, PermissionError):
            continue
    # Prefer the agent itself over the shell that launched it.
    for pid, comm in candidates:
        if comm == "pi" or comm.startswith("python"):
            return pid
    return candidates[0][0] if candidates else None


def stalled(worktree: str, log: str | None = None, pid: int | None = None,
            window: int = 60) -> dict:
    """Is an agent stuck? Three signals, because one is a guess.

    A quiet log is not a stall: pi writes its transcript at the end, and reading "idle 708s" as
    dead was wrong three times. A stall is the process alive, the log flat across a real window,
    **and** nothing it edits touched for far longer. When those three agree it is stuck; when
    they disagree, say which.
    """
    code, out, _ = run("git status --porcelain", cwd=worktree)
    edited = [str(Path(worktree) / line[3:].strip()) for line in out.splitlines() if line[3:].strip()]
    before = Path(log).stat().st_size if log and Path(log).exists() else 0
    time.sleep(window)
    after = Path(log).stat().st_size if log and Path(log).exists() else 0
    newest = newest_mtime(edited)
    idle_edit = (time.time() - newest) if newest else None
    running = alive(pid) if pid else None
    return {
        "process_alive": running,
        "log_growth_bytes": after - before,
        "seconds_since_last_edit": None if idle_edit is None else round(idle_edit),
        "stalled": bool(running) and (after - before) == 0
                   and idle_edit is not None and idle_edit > max(600, window * 5),
    }


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "alive":
        print(alive(int(sys.argv[2])))
    elif what == "run":
        code, out, err = run(sys.argv[2])
        print(f"exit={code}")
        print((out + err)[-2000:])
        sys.exit(code)
    elif what == "footer":
        print(footer_count(sys.argv[2], sys.argv[3]))
    elif what == "stalled":
        import json
        print(json.dumps(stalled(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None,
                                 int(sys.argv[4]) if len(sys.argv) > 4 else None), indent=2))
    else:
        print(__doc__)
