#!/usr/bin/env python3
"""Launch and observe PI runs without hand-rolling a check that can lie.

Every wrong call made about a PI run here came from an ad-hoc instrument:
a `grep` built from the install path (PI appears in `ps` as `pi`, so it matched
nothing whether PI ran or not), and a `| tail -N` on a live run (tail buffers,
so the output file stays empty while PI works). Both fail silently, and both
fail towards "nothing is running" — the answer that invites a duplicate launch.

    pilot.py start  --unit W3 --task review --cwd DIR --brief FILE
    pilot.py status [--json]
    pilot.py log    RUN_ID [--lines N]
    pilot.py stop   RUN_ID
    pilot.py selftest

`selftest` is the point: it proves status can report BOTH running and finished,
using a throwaway process and no model credit. Run it before believing a
negative answer.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RUNS = Path(os.environ.get("PI_PILOT_HOME", Path.home() / ".local/state/pi-pilot"))
PI = Path.home() / ".local/bin/pi"
DEFAULT_MODEL = "minimax/MiniMax-M3"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def proc_identity(pid):
    """(comm, starttime) for a live pid, or None. starttime defeats pid reuse."""
    try:
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
        stat = Path(f"/proc/{pid}/stat").read_text()
        # field 22 is starttime; the comm field may contain spaces, so cut at ')'
        starttime = stat[stat.rindex(")") + 2:].split()[19]
        return comm, starttime
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
        return None


def is_live(rec):
    """Liveness by pid + kernel start time. Deliberately NOT by `comm`.

    PI is launched through a shell wrapper that `exec`s node, and node then renames
    itself to `pi`. Whether `Popen` returns before or after that rename is a race, so
    a run recorded as `node` and later reporting `pi` was declared dead six seconds
    after it started while it went on working for another hour. Start time is stable
    for the life of a pid and already defeats pid reuse, which is the only thing the
    `comm` comparison was there for.
    """
    ident = proc_identity(rec["pid"])
    if ident is None:
        return False
    return ident[1] == rec["starttime"]


def load_runs():
    RUNS.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(RUNS.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def describe(rec):
    live = is_live(rec)
    log = Path(rec["log"])
    size = log.stat().st_size if log.exists() else 0
    age = int(time.time() - log.stat().st_mtime) if log.exists() else None
    d = dict(rec, live=live, log_bytes=size, log_idle_seconds=age)
    if not live:
        d["exit_marker"] = Path(rec["log"] + ".exit").read_text().strip() \
            if Path(rec["log"] + ".exit").exists() else "unknown"
    return d


def cmd_start(a):
    runs = [r for r in load_runs() if is_live(r)]
    clash = [r for r in runs if r["unit"] == a.unit and r["task"] == a.task]
    if clash and not a.force:
        sys.exit(f"refusing: {clash[0]['run_id']} is already running {a.task} for {a.unit} "
                 f"(pid {clash[0]['pid']}). Pass --force to run a second one anyway.")

    brief = Path(a.brief).read_text()
    if not brief.strip():
        sys.exit(f"refusing: brief {a.brief} is empty")
    if not PI.exists():
        sys.exit(f"pi not found at {PI}")

    run_id = f"{a.unit}-{a.task}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    RUNS.mkdir(parents=True, exist_ok=True)
    log = RUNS / f"{run_id}.log"
    # never a pipe: a pipe through tail is why a live run once looked dead
    fh = open(log, "wb")
    env = dict(os.environ, PATH=f"{Path.home()}/.local/bin:{os.environ.get('PATH','')}")
    argv = [str(PI), "-p", "--model", a.model, "--thinking", a.thinking,
            "--session-id", a.session or run_id, brief]
    p = subprocess.Popen(argv, cwd=a.cwd, stdout=fh, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    ident = proc_identity(p.pid)
    if ident is None:
        sys.exit(f"pi exited immediately; see {log}")
    rec = {"run_id": run_id, "pid": p.pid, "comm": ident[0], "starttime": ident[1],
           "unit": a.unit, "task": a.task, "cwd": str(Path(a.cwd).resolve()),
           "session_id": a.session or run_id, "model": a.model,
           "log": str(log), "brief": str(Path(a.brief).resolve()), "started": now()}
    (RUNS / f"{run_id}.json").write_text(json.dumps(rec, indent=2))
    print(f"{run_id}  pid {p.pid}  log {log}")
    print(f"watch:  python3 scripts/pi/pilot.py wait {run_id}")
    print("        run that as a tracked job — a detached run is invisible to anyone "
          "who does not think to ask")


def cmd_status(a):
    recs = [describe(r) for r in load_runs()]
    if a.json:
        print(json.dumps(recs, indent=2))
        return
    live = [r for r in recs if r["live"]]
    print(f"LIVE ({len(live)})")
    for r in live:
        print(f"  {r['run_id']:<34} pid {r['pid']:<7} {r['log_bytes']:>9} B  "
              f"idle {r['log_idle_seconds']}s  {r['cwd']}")
    if not live:
        print("  none — run `selftest` before treating this as evidence")
    done = [r for r in recs if not r["live"]]
    if done:
        print(f"\nFINISHED ({len(done)})")
        for r in done[-8:]:
            print(f"  {r['run_id']:<34} {r['log_bytes']:>9} B  exit {r['exit_marker']}")


def cmd_log(a):
    for r in load_runs():
        if r["run_id"] == a.run_id:
            p = Path(r["log"])
            if not p.exists():
                sys.exit(f"log missing: {p}")
            lines = p.read_text(errors="replace").splitlines()
            print("\n".join(lines[-a.lines:]))
            return
    sys.exit(f"no such run: {a.run_id}")


def cmd_stop(a):
    for r in load_runs():
        if r["run_id"] == a.run_id:
            if not is_live(r):
                sys.exit(f"{a.run_id} is not running")
            os.killpg(os.getpgid(r["pid"]), signal.SIGTERM)
            time.sleep(1)
            print(f"{a.run_id}: {'still live' if is_live(r) else 'stopped'}")
            return
    sys.exit(f"no such run: {a.run_id}")


def cmd_wait(a):
    """Block until a run ends, printing progress. Run this in the foreground or as a
    tracked background job so the run is visible to whoever is watching, not just to
    whoever thinks to ask `status`."""
    rec = next((r for r in load_runs() if r["run_id"] == a.run_id), None)
    if rec is None:
        sys.exit(f"no such run: {a.run_id}")
    log = Path(rec["log"])
    while is_live(rec):
        size = log.stat().st_size if log.exists() else 0
        print(f"[{now()}] {a.run_id} running, log {size} B", flush=True)
        time.sleep(a.interval)
    size = log.stat().st_size if log.exists() else 0
    print(f"[{now()}] {a.run_id} finished, log {size} B")
    if log.exists():
        print("\n".join(log.read_text(errors="replace").splitlines()[-a.lines:]))


def cmd_selftest(a):
    """Prove status reports running AND finished. No model credit spent."""
    RUNS.mkdir(parents=True, exist_ok=True)
    log = RUNS / "selftest.log"
    # A process that RENAMES itself, because the real subject does: pi is exec'd as
    # node and then sets its own process title. A `sleep` would pass this test while
    # the instrument was blind to the only case that has ever broken it.
    p = subprocess.Popen(
        ["python3", "-c",
         "import setproctitle,time" if False else
         "import time,ctypes;"
         "ctypes.CDLL(None).prctl(15, b'renamed-probe', 0, 0, 0);"
         "time.sleep(30)"],
        stdout=open(log, "wb"), stdin=subprocess.DEVNULL, start_new_session=True)
    ident = proc_identity(p.pid)
    assert ident, "selftest: could not read a process it just started"
    rec = {"pid": p.pid, "comm": ident[0], "starttime": ident[1], "log": str(log)}
    time.sleep(1)  # let it rename itself
    renamed = proc_identity(p.pid)
    ok_rename = renamed is not None and renamed[0] != ident[0]
    ok_live = is_live(rec)
    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    p.wait(timeout=5)
    ok_dead = not is_live(rec)
    print(f"the probe really did rename itself:      {'yes' if ok_rename else 'NO — test is weaker than it looks'}")
    print(f"reports a running, RENAMED process as live: {'PASS' if ok_live else 'FAIL'}")
    print(f"reports a killed process as dead:           {'PASS' if ok_dead else 'FAIL'}")
    sys.exit(0 if (ok_live and ok_dead and ok_rename) else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="launch a PI run")
    s.add_argument("--unit", required=True)
    s.add_argument("--task", required=True, help="review, implement, fix …")
    s.add_argument("--cwd", required=True)
    s.add_argument("--brief", required=True)
    s.add_argument("--model", default=DEFAULT_MODEL)
    s.add_argument("--thinking", default="high")
    s.add_argument("--session", default=None)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("status", help="what is running, measured not guessed")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("log", help="tail a run's log, from the file")
    s.add_argument("run_id")
    s.add_argument("--lines", type=int, default=60)
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("stop", help="stop a run")
    s.add_argument("run_id")
    s.set_defaults(fn=cmd_stop)

    s = sub.add_parser("wait", help="block until a run ends, printing progress")
    s.add_argument("run_id")
    s.add_argument("--interval", type=int, default=60)
    s.add_argument("--lines", type=int, default=60)
    s.set_defaults(fn=cmd_wait)

    s = sub.add_parser("selftest", help="prove status can say both running and finished")
    s.set_defaults(fn=cmd_selftest)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
