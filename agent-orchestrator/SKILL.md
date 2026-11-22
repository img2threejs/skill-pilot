---
name: agent-orchestrator
description: Orchestrate external coding agents (codex gpt-6.2-sol / gpt-6.2-astra / gpt-6.1-terra, pi MiniMax-M3) through an OpenSpec round — proposal, two-reviewer red team, code, self review, two independent reviews, adjudication, real test — with every run audited. Use when the user asks Claude to act as orchestrator, delegate coding to codex/pi, "let the agents do it", or run a feature/fix through the full OpenSpec + review pipeline.
---

# Agent orchestrator

Claude orchestrates and decides; external agents do the work. This skill binds the role contracts
`agent-coder`, `agent-reviewer`, `agent-adjudicator`, `agent-distil` and `openspec-review-workflow` to the
measured roster, launchers, budget and audit below. Read those skills when a phase names them.

Consult the project's capability probes and audit lessons. Re-check the roster with
`agent-audit/scorecard.sh` from the project root before a round.

## Budget

Claude spends tokens only on
decisions: briefs, adjudication, final gate. Exploration, drafting, reading large logs, coding, reviewing and
distilling go to agents. Read agents' `out.md` reports and diffs, using the gap matrix for independent reviews.
If codex and pi are both unavailable, mark the round BLOCKED and ask the owner.

## Roster

| Role | Agent / model | Launch |
|---|---|---|
| Exploration, repo Q&A, OpenSpec draft, hard implementation, reviewer | codex `gpt-6.2-sol` | brief says: smallest diff, no new abstractions (Sol overengineers) |
| Normal implementation, fixes, UI / visual / browser verification, reviewer | codex `gpt-6.1-terra` | effort `low` for small tasks, `medium` default |
| Escalation: Sol failed twice, review loop failed twice, security / auth / money, cross-repo design | codex `gpt-6.2-astra` | costs ~4x Sol quota; name the reason in the brief |
| Red team, independent reviewer, parallel worker on a fully specified task | pi `minimax/MiniMax-M3` | verify every "done" against artifacts; findings are verbose, filter them |

Not used: opencode, gpt-6-luna, gpt-6.1-sol, gpt-6.2-astra as a default. Report an unavailable runtime with its exact
error and mark the round BLOCKED; never fall through to an undeclared agent.

## Launch: `scripts/dispatch.sh`

Always launch through `scripts/dispatch.sh` relative to the directory containing this file.
Set `SKILL_DIR` to that directory and `PROJECT_ROOT` to the directory containing your checkouts for the examples below.
herdr is the default for writers and readers.
On `HERDR_NOT_RUNNING`, the orchestrator starts the server itself without stealing focus:
`tmux has-session -t herdr-host || tmux new -d -s herdr-host herdr`. The owner watches by running `herdr` in any
terminal, which attaches to the same server. Then it re-dispatches. Dispatch never falls back to `--via exec`
automatically. Dispatch closes stdin for headless runs,
enforces a timeout, and captures the log and report. Before launching codex, dispatch disables enabled MCP servers
declared in `${CODEX_HOME:-$HOME/.codex}/config.toml` and every server table in each `.codex/config.toml` from the run checkout up to its repo top,
including project servers Codex only sees after folder trust. Dispatch uses Python 3.11 or later to parse these files.
A parse error, unsafe server name on a disable flag, or enabled undeclared server aborts the run with
`CODEX_MCP_LIST_FAILED:<short cause>`. The cause uses only `[A-Za-z0-9_.:-]` and is limited to 60 characters.
Enabled undeclared built-ins are recorded as `MCP_BUILTIN_ON=<names>`. Dispatch checks
the exec log for headless codex and matches the prompt's unique run marker in a rollout under
`${CODEX_HOME:-$HOME/.codex}/sessions` for herdr codex. If these checks find no model, dispatch records the
requested model with `MODEL_UNVERIFIED`. For pi, dispatch passes `--model` and records the requested model
with `minimax/` added if unqualified.
Dispatch flags read-mode worktree changes and writes a `.kv` record.

```bash
D="$SKILL_DIR/scripts/dispatch.sh"
# writer in an isolated worktree, visible in herdr
"$D" --round "$R" --il "$PROJECT_ROOT" --label code-1 --agent codex --model gpt-6.1-terra --access write \
   --cwd <repo> --brief $R/briefs/code-1.md --phase code
# send a correction to the author in the same session and worktree
"$D" --round "$R" --il "$PROJECT_ROOT" --label code-2 --resume code-1 --agent codex --model gpt-6.1-terra --access write \
   --cwd <repo> --brief $R/briefs/code-2.md --phase code
# read-only reviewer in a fresh detached checkout, visible in herdr
"$D" --round "$R" --il "$PROJECT_ROOT" --label rev-pi --agent pi --model minimax/MiniMax-M3 --access read \
   --cwd <review-worktree> --brief $R/briefs/review.md --phase review
# explicit fallback when herdr is unavailable
"$D" --round "$R" --label rev-exec --agent codex --model gpt-6.2-sol --access read --via exec \
   --cwd <review-worktree> --brief $R/briefs/review.md --phase review
```

- The owner watches agents in herdr. Dispatch probes the server before launch and records
  `HERDR_NOT_RUNNING` if the connection is refused.
- Each project root gets a dedicated, skill-owned herdr workspace. Dispatch records its workspace ID,
  label, cwd and creation time in `<skill dir>/state/herdr-home.json`, outside Git, keyed by the canonical
  project root. A mkdir lock serializes
  provisioning. Dispatch reuses the recorded workspace when its ID and label both match the live listing.
  Otherwise it creates a background workspace rooted at the project root and atomically saves its identity.
  Each provisioning request has a 10-second deadline and a 2-second kill grace period. A create timeout
  reports `HERDR_HOME_TIMEOUT`. Dispatch keeps the per-project marker until it saves a valid create receipt.
  If the marker remains, a retry reports `HERDR_HOME_CREATE_UNCERTAIN` and logs the marker path.
  Check Herdr and resolve any unrecorded workspace before clearing the marker and retrying.
  The creation label comes from `--herdr-home <label>`, then `DISPATCH_HERDR_HOME`, and defaults to `img2`.
  When testing from a source checkout, point `DISPATCH_HERDR_STATE_DIR` to a state directory outside Git.
  Dispatch leaves unrelated workspaces and tabs alone. It only reads terminal output,
  sends input to, or closes the tabs and panes it created and tracks for the round.
- For both herdr access modes, including resume, pass the project root with `--il` or set `HERDR_IL_PATH`.
  `--il` takes precedence. If neither supplies a value, dispatch prints `HERDR_IL_REQUIRED` and exits 2.
  The checkout must be inside the project root. Exec launches and `--close` can run without this setting.
  For writers, dispatch creates `<il>/<repo>-wt-<label>` on `agent/<label>` and keeps both for review. It flags source repo changes, including
  edits to already-dirty files, with `EDITED_SOURCE_REPO` and direct sibling repo snapshot changes with
  `EDITED_SIBLING_REPO <name>`. The source snapshot excludes only `<round>/runs/` when the round is inside the source repo.
  Removed siblings give `outcome=error` with `SIBLING_REMOVED <names>`. Added siblings are listed in `SIBLING_SET_CHANGED <names>` without changing the outcome.
  The sibling audit excludes the source repo, the run's own checkout and the round's repo, and records all other sibling names before and after the run.
  Fingerprint comparisons cover siblings present at both snapshots, except those that started as detached
  linked worktrees named `*-rv-*` or linked worktrees on `agent/*` branches. The writer puts its report in
  `AGENT_REPORT.md` at the worktree root.
  Dispatch records the branch and worktree in an `ABORTED` record as soon as it creates them and replaces
  that record at closeout.
- For herdr readers, dispatch uses the supplied detached checkout and sets TMPDIR to a fresh `runs/<label>.tmp`.
  A pi reader runs as a pane command under `sandbox-exec` with `--no-session --tools read,bash`. If the sandbox
  fails to start, pi cannot launch. The pane runs a short launcher from scratch and reads its jq filter from a file.
  Oversized pane commands and agent launches report `HERDR_PANE_INPUT_TOO_LONG` before submission. A codex
  reader runs as a herdr agent with `-s workspace-write --add-dir <scratch>`
  and writes `REPORT.md` in scratch.
- Dispatch creates one background tab in the home workspace for either access mode. A herdr agent completes with
  done or idle status and a fresh, non-empty report. A pi reader's pane command signals completion with its
  exit status. An empty report records `NO_REPORT`. The startup recovery wait allows 60 seconds and retries
  once when herdr returns `timeout`. A block during the prompt records `AGENT_BLOCKED`.
- Reviewers always use fresh sessions, including self review.
  Readers save any available report to `runs/<label>.out.md`, capture their pane and close their tab on exit.
  A timeout, execution error or interrupt with saved reader text records `PARTIAL_REPORT`. Dispatch sends Ctrl+C
  before closing a timed-out writer or pi reader. The run record marks successful closure with
  `herdr_closed=1`. Dispatch closes a new tab on startup failure, including `AGENT_BLOCKED_AT_START`
  and `HERDR_TAB_NO_PANE`. If that close fails and the receipt lacked a pane, `--close` can retry using
  the recorded workspace, tab ID and label. Writers keep their tab after other closeouts and record
  `herdr_workspace`, `herdr_tab`, `herdr_pane`, agent name, worktree path, branch, agent kind and model. On INT or TERM,
  dispatch sends Ctrl+C to the run pane when available before closing the tab.
- Send-backs to a coder use `--resume <author-run-label>` with a new run label. Dispatch requires a recorded
  herdr writer with a live tab and an idle or done agent in the recorded pane, and reuses that tab, pane,
  worktree and branch. A missing tab reports `RESUME_REFUSED:tab_gone`. Pass the original source checkout
  as `--cwd`. The new brief has its own run marker, timeout, report
  and audit. The record includes `resumed_from`.
  Dispatch verifies the latest model in the live Codex session's rollout before prompting. A previous
  `MODEL_UNVERIFIED` record or an unavailable live model (including pi) refuses resume. A refusal exits
  non-zero with `RESUME_REFUSED:<cause>`.
- Before launching a new writer, dispatch closes the oldest idle writer tabs in the same round until
  at most four remain. Working and blocked agents stay open. Each closure appears as `CLOSED_IDLE <label>`
  in the new run's note.
- `--via exec --access write` runs directly in the supplied `--cwd`, with no worktree creation or source or sibling
  audit. The orchestrator must pass a worktree it created itself, as it does for skill development.
- Exec readers write temporary files under the same fresh TMPDIR and return their report in the final
  message. pi reviewers in both launchers run under `sandbox-exec`, with writes limited to TMPDIR,
  `~/.pi/agent/settings.json.lock`, `~/.pi/agent/auth.json.lock`, and required devices.
  A change to the pi state fingerprint (path, size, mtime and inode, excluding `sessions/`, `auth.json`,
  `models-store.json`, and `*.lock`) records `outcome=error` with `EDITED_PI_STATE`.
  A checkout change caught by the snapshot records `outcome=error` with `EDITED_IN_READ_MODE`; discard that
  review and restore the worktree before the next run.
- Reviewer briefs cap findings at 15 total. Report high and medium findings and at most three low findings.
  Use one line per finding, `severity | file:line | defect | evidence`, followed by a verdict.
- pi runs default to 1500 seconds. pi exec runs and pi herdr readers save JSON events to
  `runs/<label>.events.jsonl` and extract assistant replies into the report. The herdr pane also shows tool
  starts and failures.
  An otherwise successful run with an empty report records `outcome=error` with `NO_REPORT`.
- Run independent dispatches in parallel (`&` + `wait`, or `run_in_background`). Keep parallel writers in separate
  worktrees.
- When checking progress, look for changes in files or pane output. Dispatch captures the recent herdr pane output
  at the end of the run and on abort.

## Round setup

1. Confirm the target repo inside the project root. Read its `AGENTS.md` /
   `CLAUDE.md` and any `reviewer-style-profiles.md`; inline the relevant rules into every brief, since agents start
   with empty context.
2. Create the round at `$PROJECT_ROOT/agent-audit/rounds/<YYYY-MM-DD>-<slug>` and set `R` to that directory. Create `briefs/`, `reviews/`,
   `evidence/` and `runs/`. Every brief is a file in `briefs/` that carries exact in-scope and out-of-scope paths
   and acceptance checks. Append the full body of the applicable role contract (`agent-coder/SKILL.md` or
   `agent-reviewer/SKILL.md`) to the brief.
3. Use the project's existing OpenSpec root. Never run `openspec init`
   and never create a new `openspec/` inside a code repo.

## Pipeline

Each phase writes its artifacts into `$R` and ends with an audit record. Stop and ask the owner when scope or a
product decision is unclear; do not let an agent guess it.

1. **Explore** with Sol, read-only. It returns current behavior, affected files and symbols, tests, risks and open
   questions. Claude reads the report and writes the proposal brief.
2. **Proposal** by Sol, writing the OpenSpec change (proposal, design when needed, specs, tasks) per
   `openspec-review-workflow`.
3. **Red team**: at least two blind reviewers, read-only, in parallel. Default pi as the architecture adversary and
   Terra as the delivery adversary. Apply the reviewer model rules in step 6. Then a debate pass: each
   reviewer gets the other's raw report and answers accept / rebut / amend. Claude builds the gap matrix, decides
   every high and medium finding, and Sol fixes the artifacts. Loop until `openspec validate <change> --strict`
   passes and no material finding is open; after 3 loops, escalate to the owner.
4. **Code** per `agent-coder` in a worktree visible in herdr. Pick the coder from the roster. The round records
   the author. A failing probe before the fix is required for bug fixes.
5. **Self review**: a fresh read-only run of the author model on its own diff, per `agent-reviewer`. The author then
   fixes, or justifies in writing, every finding and leaves the work uncommitted. The codex sandbox blocks writes
   to `.git`. The orchestrator reviews `git status` and the diff, then commits locally on the worktree branch.
   This review commit stays local.
6. **Independent review**: at least two reviewers per `agent-reviewer`, fresh sessions, read-only, in parallel, given
   the brief, the OpenSpec specs and tasks, and the diff but never the self review or each other's output. Each
   reviewer states `implemented`, `missing`, or `wrong` for every requirement and scenario. Give each reviewer a
   fresh detached checkout of the coder's commit with `git -C <repo> worktree add --detach <il>/<repo>-rv-<label> <sha>` and remove
   it afterwards. Reviewer models never include the author model, and at least one reviewer is from the other
   family. The default is pi plus another codex model for a codex author, and Sol plus Terra for a pi author.
   For security, auth or money, include Astra unless Astra authored the work, in which case use Sol plus pi.
7. **Adjudicate** (Claude, per `agent-adjudicator`): first, Terra in read mode collates both raw reviews into one
   gap matrix. Deduplicate findings and record agreement or disagreement with file:line references. Claude reads
   the matrix and opens raw reports only for disagreements. Verify each finding against code and evidence and run
   it when two reviewers disagree; the vote does not decide. Check the author's written justifications for self-review
   findings. Record any `SEND BACK WITH <items>` in `$R/decision.md`. A send-back goes to the coder, then back to
   self review (step 5) and independent review (step 6). Two send-backs on the same item → re-assign the coder to Astra.
8. **Real test**: run the repo's own gates and an end-to-end check of the actual behavior. Terra drives UI and browser
   checks; img2threejs visual work follows its screenshot gate. Claude reads the outputs itself and saves them to
   `$R/evidence/`, mapping every OpenSpec scenario to evidence. Re-run `openspec validate <change> --strict`
   before close. A test or validation failure is a send-back through step 5 and step 6. Write `MERGE` to
   `$R/decision.md` only after the real test and validation pass.
9. **Close**: aside from the local review commit in step 5, code repo commits, pushes, PRs and merges require
   the owner's approval. Follow the project's commit attribution policy.
   When a writer batch is accepted, run `$D --round $R --close <label>` for each writer. Closing an already
   closed tab reports a no-op. After the round closes (`MERGE` or abandonment), close any remaining recorded
   run tabs and keep the skill-owned home workspace for future rounds. Remove the `<il>/<repo>-rv-<label>` review
   checkouts, and remove `<repo>-wt-<label>` and its
   `agent/<label>` branch. When removing a Codex worktree, also remove its exact `[projects."<wt>"]` trust
   entry from `~/.codex/config.toml` if present. Record the cleanup in `decision.md`.
   Sol runs `agent-distil` on `$R`; Claude accepts or rejects each proposed lesson and skill diff; accepted lessons go
   to `agent-audit/lessons.md` with the round link.

## Audit

After verifying each run, append it:

```zsh
A="$PROJECT_ROOT/agent-audit"
$A/log-run.sh ${(f)"$(<$R/runs/<label>.kv)"} claimed_done=<true|false> verified_done=<true|false> \
  findings=<n> findings_accepted=<n>
```

`verified_done` is Claude's check of the artifacts, not the agent's claim. `agent-audit` is the orchestrator's
local log repo. Local commits are allowed there and are never pushed. `$A/scorecard.sh [phase]` shows passes,
failures, hangs, errors, false-done, review precision and time per model. When a model's
numbers drift, propose a roster change to the owner with the scorecard as evidence.

## Residual risks

- The pi read sandbox restricts writes only. Reads and network access stay open.
- Dispatch cannot disable the Codex built-in `cua_repl`. Disabling it with `-c` makes Codex exit with `invalid transport`.
- Reviewers could alter other runs' files under `runs/`. The orchestrator verifies every `.kv` against artifacts before logging.

## Known traps (measured)

- Agents misreport their model: codex wrote `GPT-6` while running `gpt-6.1-terra`. `dispatch.sh` checks codex logs.
- Codex startup can stop at the folder-trust or update menu. Dispatch passes `-c check_for_update_on_startup=false`
  and answers only the folder-trust menu (Enter, records `TRUST_ACCEPTED`). Any other menu (hook trust, update)
  stops launch with `AGENT_BLOCKED_AT_START`. Never send Escape to codex: it means "Back to Agent Command
  Center", which opened an unrelated live conversation of the owner's (measured).
- `herdr pane read` prints plain text; `agent`/`workspace` commands print JSON.
- A backgrounded run without `< /dev/null` fails at once or blocks until timeout. `dispatch.sh` closes stdin.
- A stub reviewer deleted the owner's real `~/.codex/sessions`. Use a fake HOME under TMPDIR for every stub run.
- Agents skip required output files and blame the environment. Check the artifact, not the message.
- Synthetic review probes overstate review skill. Weigh real-round precision from the scorecard over probe results.
