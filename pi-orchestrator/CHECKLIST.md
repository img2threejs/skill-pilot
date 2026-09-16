# Checklist — read before each action, not after

Every line here exists because it was got wrong at least once. Count in brackets.

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
- [ ] **`$?` after a pipe is the last command's status, not the one you care about** [3].
      `cmd | tail -3; echo $?` reports `tail`. Redirect to a file and read `$?` on its own line.
      This has produced a false "exit=0" on a run that exited 124, and twice more since.
- [ ] **Open a grep hit before dismissing it as noise** [1]. `AGENTS.md` appearing inside a
      harness's own source was read as the harness documenting itself; it was the loader, and the
      verdict written from that dismissal was wrong in the file for a day.
- [ ] **Grep for the thing, not for text about the thing** [2]. An unanchored search matched a
      commit body saying "no Co-Authored-By trailer", and a comment explaining why
      `single-page-application` is *not* set. Anchor, or read the match before believing it.
- [ ] **Never cast a probe's arguments to silence the compiler** [1]. An `as never` on a config
      object hid that `repo` is `{owner, repo}` and not a string; the call reached GitHub as
      `repos/undefined/undefined/...`, returned 404, and the publisher's own "the repo does not
      exist" message made it look like a product defect. The type system was the check, and the
      cast was me turning it off.
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
