---
name: pi-instruments
description: Measure, don't infer — the blind-instrument catalogue. Read before concluding anything from a command's output.
---

# Measure, don't infer

Almost no wrong conclusion in agent work is a reasoning error. They are instrument errors: **someone
trusted an operation instead of measuring its result.** Every case below is real, every one was cheap
to catch, and none of them required being smarter — only checking that the instrument could have
returned the answer.

## The rules

**Read, don't count.** `grep -c` reports lines matching a pattern, which is not the number of things
that happened. Four lines matching `FAILED` in one verifier's output were the *event payloads of
checks that passed* — `"the upstream response failed after the credential"`. The run was `exit 0`
with 101 `ok`. A count is a hypothesis; the lines are the measurement.

**Agreement between two blind instruments is not confirmation.** `find -maxdepth 4` on a path six
levels deep and `ls -lat | head -6` on a directory of eight files agreed that a file did not exist.
Both were structurally incapable of seeing it. When two checks agree, ask whether they could both be
blind the same way — especially when they are the same *kind* of check.

**Never conclude "nothing happened" from an empty log.** Read artefacts first, in this order: `git
log`, `git status`, the output directory. An agent whose log was 91 bytes had ten files edited and
uncommitted in the working tree. Another, judged to have produced nothing, had already posted a 25 KB
review to a pull request. **If the tree is dirty, commit it as WIP before you judge it** — concluding
"it did nothing" destroys work that is already there.

**Do not measure a tree while something is mutating it.** A verifier reporting `exit 1` reported
`exit 0` on the same commit minutes later, because an agent was mid-way through its own test when the
first measurement ran. Wait for it to finish, then measure.

**When a setup step fails twice, stop improving your script and look for the committed one.** Three
consecutive attempts to stand up a database by hand failed on three different self-inflicted
problems, on a day when the same measurement was made correctly, first try, by an agent that used the
project's own verifier instead of writing its own.

## The catalogue

| What was run | Why it could not work |
|---|---|
| `grep '[c]li.js'` for an agent process | The launcher execs `node`, which renames itself. The pattern could never match; it hid three live processes, one an hour-old orphan. |
| `cmd \| tail -30` to check progress | `tail` buffers. The 0-byte read was the pipe, not the process. |
| `pg_isready` right after `docker run postgres` | Postgres starts, initialises, and **restarts**. The first ready is the bootstrap instance. Wait for the *second* `database system is ready to accept connections` in `docker logs`. |
| `kill <npm pid>` for a dev server | `npm run dev` spawns the bundler as a child, and the child holds the port. Kill both pids and verify with `ss -tln`. |
| `pkill -f "npm run dev"` | Matches your own shell. It killed the command that was about to run the verifier. Resolve the pid from `ss -tlnp` and kill that. |
| `git diff ORIG_HEAD HEAD` after `filter-branch` | ORIG_HEAD is not the pre-rewrite tip. Use `refs/original/refs/heads/<branch>`. |
| `json.dump(..., ensure_ascii=False)` on a file written with `\uXXXX` escapes | Rewrites every line containing a non-ASCII character. A two-entry addition produced a 19-line diff — twice in one session. Match the file's existing encoding, or edit textually. |
| `git checkout --ours <file>` on a conflicted shared file | Takes the **whole** file, silently reverting everything the other side added. Resolve by construction: take the base, re-apply your side's entries programmatically, then verify against **both** merge parents. |
| `INSERT` naming a generated column | Postgres refuses the statement before it evaluates your CHECK, so the measurement never runs. Insert only the columns you own. |
| `docker run` with an `initdb/` mount and no extra env | An init script missing a required variable exits non-zero and the **container dies**, so every later `docker exec` fails for an unrelated reason. |
| A self-test whose probe is a `sleep` | If the property is "survives a rename", the probe must rename itself — and the test must assert the rename happened. |

## Before you report a measurement

- Did the instrument have a path to the answer, or only to the answer you expected?
- If it returned nothing, can it return anything? Run it against a case you know is positive.
- If you counted, read the lines.
- If something else was running, run it again after that finished.
