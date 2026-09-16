"""Is the agent getting anywhere, or just still breathing?

Every liveness signal this project has built answers the wrong question. A wedged agent and a
working one both have a pid; an agent looping one failing command appends a transcript turn every
few seconds and reads as WORKING forever. Measured: pg-15 ran the same `demonstrate-gate-denial`
command four times, ten minutes apart, for eighty minutes, while the watcher reported WORKING the
whole way.

Progress is a different measurement from liveness, and it is visible in PI's own transcript:

    LOOPING   the recent commands repeat, or the same failure keeps coming back
    GRINDING  turns are being spent but nothing is being produced
    MOVING    commands are varied and files or commits are appearing
"""
import json
import re
import time
from collections import Counter
from pathlib import Path

WINDOW = 12          # how many recent tool calls to judge
REPEAT_LIMIT = 3     # the same command this many times in the window is a loop
GRIND_SECONDS = 1800


def _normalise(command: str) -> str:
    """Reduce a command to the action it performs, dropping how its output is caught.

    An agent retrying does not retype the command: it changes the timeout, swaps `| tail -30` for
    `| head -60`, redirects to a different scratch file, appends `; echo exit=$?`, or backgrounds
    it with `&`. Measured on pg-15's recorded loop: seven of thirteen commands in one window
    invoked `scripts/demonstrate-gate-denial.mjs` and differed only in those ways. Comparing whole
    command lines saw seven distinct steps and reported healthy variety; comparing actions sees one
    thing tried seven times, which is what it was.
    """
    text = re.sub(r"#[^\n]*", " ", command)                   # its own thinking-aloud comments
    first = re.split(r"[|;&]|>>|>|\n", text)[0]               # the action, not the plumbing
    first = re.sub(r"\btimeout\s+\d+\b", "", first)          # the retry knob it keeps turning
    first = re.sub(r"\b\d+\b", "N", first)                    # other numbers that drift
    first = re.sub(r"\s+", " ", first)
    # `2>&1` splits at the `>` and leaves a bare stream number behind, which would make
    # `script.mjs 2>&1` and `script.mjs` read as two different actions.
    first = re.sub(r"\s+N\s*$", "", first)
    return first.strip()[:120]


def _signature(output: str) -> str:
    """A short, drift-free fingerprint of a command's output.

    Paths, pids, timings and byte counts change between two runs of the same failing command, so
    they are removed; what is left is the shape of the answer. Two attempts that fail the same way
    produce the same signature.
    """
    text = re.sub(r"\b\d+(\.\d+)?(ms|s|KB|MB|B)?\b", "N", output)
    text = re.sub(r"/[\w./-]+", "P", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[-300:]


def calls(transcript: Path) -> list[tuple[str, str, str]]:
    """(timestamp, command, result-signature) per tool call, oldest first.

    The result is what separates a loop from work. `npm test` three times in a dozen calls is an
    ordinary edit-test-edit cycle when the output keeps changing, and a loop when the same failure
    comes back each time. Judging on the command alone called the first of those a loop.
    """
    out = []
    try:
        lines = transcript.read_text(errors="replace").splitlines()
    except OSError:
        return out
    pending: dict[str, tuple[str, str]] = {}
    results: dict[str, str] = {}
    order: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message", {})
        for chunk in (message.get("content") or []):
            if chunk.get("type") == "toolCall":
                command = (chunk.get("arguments") or {}).get("command", "")
                if command:
                    pending[chunk.get("id", "")] = (row.get("timestamp", ""), command)
                    order.append(chunk.get("id", ""))
        if message.get("role") == "toolResult":
            text = " ".join(c.get("text", "") for c in (message.get("content") or [])
                            if c.get("type") == "text")
            results[message.get("toolCallId", "")] = _signature(text)
    for call_id in order:
        if call_id in pending:
            timestamp, command = pending[call_id]
            out.append((timestamp, command, results.get(call_id, "")))
    return out


def verdict(transcript: Path, produced_recently: bool, at: float | None = None) -> tuple[str, str]:
    """Judge the window of calls ending at `at` (unix seconds; None means the whole file).

    `at` exists so the detector can be run against recorded history and asked what it would have
    said at the time — the only way to know whether it catches a loop when it starts rather than
    after someone notices.
    """
    history = calls(transcript)
    if at is not None:
        history = [(t, c, sig) for t, c, sig in history
                   if t and time.mktime(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")) <= at]
    if not history:
        return "UNKNOWN", "no transcript"

    window = history[-WINDOW:]
    counts = Counter((_normalise(c), sig) for _, c, sig in window if sig)
    if counts:
        (command, _), repeats = counts.most_common(1)[0]
        if repeats >= REPEAT_LIMIT:
            return "LOOPING", f"same command, same result {repeats}x: {command[:55]}"

    if not produced_recently:
        first = history[0][0]
        span = window[0][0]
        if span and first:
            elapsed = (time.mktime(time.strptime(window[-1][0][:19], "%Y-%m-%dT%H:%M:%S"))
                       - time.mktime(time.strptime(span[:19], "%Y-%m-%dT%H:%M:%S")))
            if elapsed > GRIND_SECONDS:
                return "GRINDING", f"{len(window)} calls over {int(elapsed // 60)}m, nothing produced"
    return "MOVING", f"{len({_normalise(c) for _, c, _ in window})} distinct actions in last {len(window)}"
