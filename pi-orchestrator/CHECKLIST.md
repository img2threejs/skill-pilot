# Checklist — read before each action, not after

Every line here exists because it was got wrong at least once. Count in brackets.

## Before launching an agent

- [ ] **`nohup` for the agent, harness background for a monitor that watches it** [2]. Neither
      alone is right: a bare `nohup … &` is invisible to the user — no chip, no notification, no
      way to stop it except by asking me — and a long agent run placed directly in a harness
      background task was killed mid-refactor with exit 144. Run the agent detached so it
      survives, and start a separate harness-tracked loop that polls its log and its worktree, so
      the user can see it and gets told when it ends.
- [ ] **Give every run a `--session-id`** [1]. It is what makes an interrupted run resumable
      with its context intact instead of restarting from nothing.
- [ ] **Worktree deps: `ln -s <main>/node_modules`**, not `npm ci` [measured: 25s vs minutes].
- [ ] **Run the suite once before handing over** [1]. A coder spent an entire run in a worktree
      where `npm test` could not start and never noticed.
- [ ] **Brief points at `AGENTS.md`; do not restate the standard** [measured: 79 → 48 lines].
- [ ] **Each agent gets its own worktree** [1]. Five reviewers sharing one, running a
      file-mutating script, left the file corrupt for 65 minutes.
- [ ] Write down session id + worktree + PID where I can find them again.

## Before believing any result — mine or an agent's

- [ ] **Reproduce at least one claim myself** [1]. "8 of 8 gates demonstrated" was accepted and
      reported to the user; the mutations only renamed an error string.
- [ ] **Which assertion failed?** [1] A suite red from `TS6133` has demonstrated nothing about
      the gate that was deleted.
- [ ] **Did the outcome change, or only the wording?** [1] Deleting a gate that leaves status
      503 and zero fetches proves nothing about that gate.
- [ ] **Commits:** author `kokorolx`, no AI footer, clean tree, nothing outside scope, no `dist/`,
      no `.env` [2 — one `.env` was staged, two commits needed rewriting].
- [ ] **Read output with the right key** [2]: `logs` not `log`.
- [ ] **A tool that returns empty is not a measurement** [1]: `bc` was absent, arithmetic
      returned empty, and the report said "no CPU — probably hung" for two healthy runs.

## Before calling something stuck

- [ ] **Log growth over ≥60s, not a single sample** [3]. PI writes at the end; "idle 708s" read
      as stuck was wrong three times.
- [ ] **Process lookup, never `pkill -f <pattern>`** [2] — the pattern matches my own shell's
      command line and kills it.

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
