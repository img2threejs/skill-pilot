# skill-pilot

The workflow half of agent-driven development: how to orchestrate rounds, what a coder is held
to, how a review is scored, how a disagreement gets settled, and how each round's lessons become
the next round's rules.

**None of it is about a particular agent.** These skills were extracted from
[pi-pilot](https://github.com/kokorolx/pi-pilot) after measuring what they actually contain: of
1,718 lines across eight skills, only pi-pilot's own 149 mention pi at all. The other seven never
mention it once. The `pi-` prefix claimed a coupling that did not exist, so it is gone.

The harness drivers live in their own repositories and are interchangeable:

- [pi-pilot](https://github.com/kokorolx/pi-pilot) — drives `pi`
- [dsh-pilot](https://github.com/img2threejs/dsh-pilot) — drives DeepSeek Harness

Both load the workspace's `AGENTS.md`, so the project's own standard reaches the agent and a
brief can describe the task instead of restating the rules.

## The skills

| | |
| --- | --- |
| `orchestrator` | decides. Plans rounds, scores them out of 50, ships or sends back, and distils what each round taught. Includes `CHECKLIST.md` — read before every launch, every verdict, every landing |
| `coder` | the standard a coder is held to: demonstrate, do not assert |
| `reviewer` | how to review so that a finding survives contact with the code |
| `adjudicator` | merges parallel reviews, settles disagreements by measuring rather than averaging |
| `prescription-verifier` | walks a prescription against the actual call sites before it is accepted |
| `distil` | turns a finished round into rules, so the next round starts further along |
| `instruments` | how to tell a working measurement from one that reports success while measuring nothing |

## The one rule the rest of it serves

A check that can only ever pass has not been shown to work. Break the property deliberately,
watch the check go red for *that* reason, restore it, and watch it go green. Most of
`CHECKLIST.md` is the record of times that was skipped and what it cost.
