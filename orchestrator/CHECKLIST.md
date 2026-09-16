# Checklist — read before each action, not after

Every line here exists because it was got wrong at least once. Count in brackets.

**Nine of them have been broken twice or more, and almost every repeat was a shell idiom retyped
by hand.** Writing the correct incantation down did not stop the wrong one: the `ps -e` trap was
recorded here and then used again by the very next tool written after it. So those rules are no
longer sentences to remember — they are functions to call.

```
orchestrator/probe.py   alive(pid) · run(cmd) · footer_count(repo, range) · stalled(worktree, log, pid)
orchestrator/sweep.py   what an agent run left behind, and what must never be killed
```

`run()` refuses a command that pipes into a filter, because its exit status would be the
filter's. A guard beats a reminder.

## Before launching an agent

- [ ] **`nohup` for the agent, harness background for a monitor that watches it** [2]. Neither
      alone is right: a bare `nohup … &` is invisible to the user — no chip, no notification, no
      way to stop it except by asking me — and a long agent run placed directly in a harness
      background task was killed mid-refactor with exit 144. Run the agent detached so it
      survives, and start a separate harness-tracked loop that polls its log and its worktree, so
      the user can see it and gets told when it ends.
- [ ] **The completion sentinel must be one the agent cannot emit** [1]. A monitor grepping
      for `EXIT=` reported the run finished; the string had come from the agent's own
      `echo "EXIT=$?"` inside a bash tool call. Use a random marker, and anchor it (`^`).
- [ ] **Give every run a `--session-id`** [1]. It is what makes an interrupted run resumable
      with its context intact instead of restarting from nothing.
- [ ] **Worktree deps: `ln -s <main>/node_modules`**, not `npm ci` [measured: 25s vs minutes].
      The cost of that speedup: every worktree shares one `node_modules`, so a branch that adds a
      dependency leaves the others stale. **Run `npm ci` in the main checkout after merging any
      branch that touched `package.json`** [1] — staging went red with `Cannot find module 'pg'`
      on a branch whose own suite was green, because the lockfile was right and the shared
      directory was not.
- [ ] **Run the suite once before handing over** [1]. A coder spent an entire run in a worktree
      where `npm test` could not start and never noticed.
- [ ] **Brief points at `AGENTS.md`; do not restate the standard** [measured: 79 → 48 lines].
- [ ] **Each agent gets its own worktree** [1]. Five reviewers sharing one, running a
      file-mutating script, left the file corrupt for 65 minutes.
- [ ] Write down session id + worktree + PID where I can find them again.

## Choosing the model for a unit

- [ ] **Declare `contextWindow` and `maxTokens` for every model you add to `~/.pi/agent/models.json`**
      [1]. pi carries a catalogue of limits for models it knows; one added through a custom
      provider falls back to **16384 output tokens**. A DeepSeek run ended with
      `stopReason: "length"` and no commit, having spent that whole budget on reasoning — the
      model's real ceiling is 393216. The verdict written here first ("DeepSeek cannot sustain a
      long argument") was a conclusion about my configuration wearing a model's name. `max_tokens`
      is a ceiling, not a spend: you pay for tokens generated, so declare the real one.
- [ ] **`stopReason` before blame** [1]. `length` means truncated, not incapable. Read it before
      concluding anything about the model.

## Never dispatch without a watch

- [ ] **`sweep.py --disk` before every dispatch** [**2**]. The disk filled twice in one day. The
      second time it took **every container down — the deployment included** — and killed a
      mid-round agent with `ENOSPC: no space left on device, write`, which reads as an agent
      failure and is not one. Cause: `docker run postgres:18` without `-v` creates an anonymous
      volume and nothing removes it. 435 were reclaimed in the morning; by the afternoon there
      were 488 holding 23 GB. Reclaim with `sweep.py --disk --kill`, and **use `--rm` on every
      throwaway container** so the next one does not accumulate.
- [ ] **Start `watch.py --loop` in the same breath as the dispatch** [1]. Fire-and-forget cost this
      project hours: an agent that died without committing, one wedged on a command that never
      returned, and one that finished an hour before anyone looked all present the same way — as
      silence. The orchestrator then learns the state only when the owner asks, which is the worst
      possible moment.

      ```sh
      python3 orchestrator/watch.py --loop 120 <worktree> [<worktree> …]
      ```

      It reports WORKING, STALLED, DONE or FAILED per worktree and names the ones needing
      attention. **FAILED is the one that matters**: no agent and nothing committed, or work left
      stranded uncommitted — the state that looks exactly like success from outside.
- [ ] **A quiet agent is not a finished one, and a finished one is not a successful one.** The
      watch separates those three; a glance at a log separates none of them.

## Before believing any result — mine or an agent's

- [ ] **Reproduce at least one claim myself** [1]. "8 of 8 gates demonstrated" was accepted and
      reported to the user; the mutations only renamed an error string.
- [ ] **Which assertion failed?** [1] A suite red from `TS6133` has demonstrated nothing about
      the gate that was deleted.
- [ ] **Did the outcome change, or only the wording?** [1] Deleting a gate that leaves status
      503 and zero fetches proves nothing about that gate.
- [ ] **Commits:** author `kokorolx`, no AI footer, clean tree, nothing outside scope, no `dist/`,
      no `.env` [2 — one `.env` was staged, two commits needed rewriting].
- [ ] **Anchor the footer check at line start**: `grep -cE "^(Co-Authored-By:|🤖 Generated with)"`
      [1]. An unanchored `grep -i "co-authored"` matched a commit body that *said* "no
      Co-Authored-By trailer", and a clean commit was amended to fix a violation that was never
      there. A check for a thing must not match text about the thing.
- [ ] **Read output with the right key** [2]: `logs` not `log`.
- [ ] **Never read `$?` after a pipe** [3]. Call `probe.run(cmd)` — it returns the command's own
      status and *refuses* a command that pipes into a filter. `cmd | tail -3; echo $?` reports
      `tail`, which produced a false `exit=0` for a run that had exited 124, twice more after
      that, and once inside the very tool written to stop it.
- [ ] **Open a grep hit before dismissing it as noise** [1]. `AGENTS.md` appearing inside a
      harness's own source was read as the harness documenting itself; it was the loader, and the
      verdict written from that dismissal was wrong in the file for a day.
- [ ] **Anchor a search for a marker** [2]. Call `probe.footer_count(repo, range)` for AI
      trailers. An unanchored grep matched a commit body that *said* "no Co-Authored-By trailer",
      and a clean commit was amended for a violation that never existed.
- [ ] **Never cast a probe's arguments to silence the compiler** [1]. An `as never` on a config
      object hid that `repo` is `{owner, repo}` and not a string; the call reached GitHub as
      `repos/undefined/undefined/...`, returned 404, and the publisher's own "the repo does not
      exist" message made it look like a product defect. The type system was the check, and the
      cast was me turning it off.
- [ ] **A tool that returns empty is not a measurement** [1]: `bc` was absent, arithmetic
      returned empty, and the report said "no CPU — probably hung" for two healthy runs.

## Kill what a run leaves behind — run `sweep.py` before and after every round

`orchestrator/sweep.py` reports leftovers; `--kill` ends them. Do not do this by hand: the
by-hand version of it nearly took production down, see below.

- [ ] **`python3 sweep.py` before launching an agent, and again after the round closes** [1].
      A server spawned by `npm test` in one worktree survived **15 hours** holding
      `127.0.0.1:24036` — the exact port the suite's own `24000 + pid % 500` produced for the next
      agent. That agent's test run waited on the bind for **1h44m** while burning 10 seconds of
      CPU, and looked exactly like a hung model. It was mine. Nothing reported it; the resource
      was gone and no instrument said so.
- [ ] **A parent of `containerd-shim` is a container's PID 1, not an orphan** [1]. Sweeping by
      hand, `node dist-server/server.mjs` and `node tools/procedural-server.mjs` were read as
      leftovers and sent SIGKILL. They were the live playground and procedural containers. Only
      the kernel's permission check across the PID namespace stopped it — that is luck, not a
      control. `sweep.py` walks the parent chain and keeps anything under a container.
- [ ] **When in doubt, keep.** Over-keeping wastes memory; over-killing takes down a deployment or
      a colleague's run. The sweep errs towards keep by design and says why for each decision.
- [ ] **Diagnose a quiet agent by file mtime, not by log growth** [1]. The log had not moved, but
      neither had any file it had edited — last write 1h44m earlier — and the CPU total agreed.
      Three signals agreeing is a stall; one is a guess.
- [ ] **Never write a liveness check by hand** [2]. Call `probe.alive(pid)`. `ps -eo pid -p <pid>`
      prints every process on the host; that form answered "182 alive" about four dead ones, and
      ran a monitor that called a finished agent live for 56 minutes.

## Before calling something stuck

- [ ] **Ask for the agent's pid by worktree, never by hand** [1]. `probe.agent_pid(worktree)`.
      A launcher's pid was passed to `stalled()` and reported a working agent as dead — the
      `bash -c` wrapper had exited while `pi` went on underneath it.
- [ ] **Never call an agent stuck from one signal** [3]. Call `probe.stalled(worktree, log,
      pid)`: it wants the process alive, the log flat across a real window, **and** nothing it
      edits touched for far longer. A quiet log alone was read as death three times; pi writes its
      transcript at the end.
- [ ] **`probe.end_matching(pattern)`, never `pkill -f <pattern>`** [4] — the pattern matches
      my own shell's command line and kills it. Written down after two occurrences and broken
      twice more since, the last time killing the watcher started two lines later in the same
      invocation and leaving two agents running unobserved. The rule is now the function:
      it skips self and every ancestor, and returns the pids it ended so the count is
      measured rather than assumed.

## Before landing

- [ ] **A new `Env` field also goes in `createEnv()`**, and check `wrangler.toml`,
      `.env.example`, `docker-compose.yml` [2 — `PROCEDURAL_ORIGIN`, then `GENERATION_ENABLED`].
- [ ] **What does this do to the deployment as it is configured today?** [1] A kill switch that
      denies on absence turns the live playground off the moment it merges.
- [ ] **A check reading generated output must rebuild or refuse** [1].
- [ ] One PR per issue. Evidence file is canonical; PR body and issue comment point at it.
- [ ] Comment on the issue with branch, PR, score, evidence. **Never close the issue.**

## After a round that taught something

- [ ] Add a **line here**, with the count. A 35-line essay in a skill is not a check and does not
      get read at the moment it is needed — which is how most of the entries above happened twice.
