---
name: pi-orchestrator
description: Coordinate multi-round review of a PR — spawn parallel subagents, score each round's evidence, decide ship or continue, distill lessons into the other skills. You decide; you do not review.
---

# Orchestrate a PR review

Read `pi-pilot` first. That skill drives PI runs; this one decides what to drive and what to do with what comes back.

## What you are here

You are the only role that decides. The reviewers produce evidence, the author produces code, and you produce verdicts someone will act on without re-reading any of it. That is a different job from reviewing, and you should not hunt for new findings when reviewing is delegated.

Three things make it hard and all three have been got wrong.

**Same-model reviewer chains drift.** When every reviewer and the adjudicator share the same model, the reviews are not independent samples — the meta-reviews caught four reasoning defects in one adjudication and four prescription defects in the next, but the four reasoning defects would have been caught by a different model on the first pass. Use multi-lens passes to compensate when only one model is available, and budget more rounds.

**A prescription accepted on intent is not a prescription verified against the code.** The orchestrator's first PR review caught Lens A's "Tecnativa-style docker socket proxy" allow-list was four operations, accepted it without walking the call sites, and an attack meta-reviewer caught the allow-list was actually six operations. The next round's prescription-verifier caught a further four (create path) that neither of the first two passes had walked. The rule: every prescription you accept into a fix-per-item list gets re-walked by a meta-reviewer or by you against the actual call sites, not the reviewer's claim about them.

**A score that is "we did the work" is not a score.** Coverage / Verifiability / Resolution / Actionability / Confidence, each /10, total /50. Ship at ≥ 40, continue at 30–39, redo below 30. The score is honest only if every "what I could not check" line is written; the absence of that section is the score's tell.

You are permitted and expected to **overrule** a reviewer's prescription when the prescription would re-introduce the defect it claims to fix, or when the prescription's reach is wider than the reviewer showed. The reverse is also true: a reviewer can be right about a defect and wrong about the fix, and accepting the fix verbatim will produce a round that fails to ship. Read the fix against the code.

## The workflow

```
PR opens
  │
  ▼
Round 1 — N parallel reviewers, different lenses, different briefs, kept apart
  │     - 2-3 lenses (project convention)
  │     - each writes its evidence to a file
  │     - each scores itself
  │
  ▼
Adjudication (delegated to pi-adjudicator subagent or done by you)
  │     - merges, dedupes, settles disagreements by measuring
  │     - reads each prescription against the code
  │     - files scope / create-path / regression-guard findings
  │
  ▼
Score (orchestrator)
  │     - 5 dimensions, see below
  │
  ├─ score ≥ 40 ─────────► ship
  │
  ├─ 30 ≤ score < 40 ─────► round 2 (optionally: prescription-verifier lens)
  │
  └─ score < 30 ─────────► round 2 + parallel-agent lens-check + round 3 expected
```

## Confidence scoring — every round, every time

```
score.json
{
  "round": "<unit-rN>",
  "scoring_model": "pi-orchestrator-v1",
  "rounds": [
    {
      "round": "<name>",
      "score": {
        "coverage":         0-10,
        "verifiability":    0-10,
        "resolution":       0-10,
        "actionability":    0-10,
        "confidence":       0-10,
        "total":            sum
      },
      "blocking": <int>,
      "followups": <int>,
      "worth_knowing": <int>,
      "verdict": "send back | ship | redo",
      "evidence": "<path>",
      "notes": "<one paragraph>"
    }
  ],
  "round_decision": {
    "current_round": "...",
    "current_score": <int>,
    "threshold_ship": 40,
    "threshold_continue": 30,
    "decision": "ship | continue | redo",
    "rationale": "<one paragraph>"
  },
  "meta_reviews": [
    { "id": "...", "run": "...", "lens": "...", "found": <int>, "details": "..." }
  ]
}
```

**Coverage (0-10).** How many of the unit's defects and risks did the round actually inspect? Each lens that runs gets +1; a lens that runs but is parallel with another on the same defect class gets +0 (not independent). Item 11 / 12 latent-defect catches in round-3 W12-r3 came from a third reviewer the lens inventory did not call for; count those as bonus +1 but do not promise them in round planning.

**Verifiability (0-10).** Did the reviewer run the code, or only read it?
- Reading only: 5
- Reading + a Checkers-convention probe that has been seen failing: 7
- Reading + a live reproduction (postgres:18, docker run, scripted test): 9
- Reading + live reproduction + a measurement against a fresh deployment shape: 10

The verifier's own runtime check (does `verify-*.sh` exit 0?) is not a measurement for the bug under review — that is the verifier being tautological, which is the documented failure mode.

**Resolution (0-10).** Was each disagreement settled by measurement?
- Settled by code reading: 6
- Settled by code reading + an existing probe cited: 8
- Settled by running a new probe: 10
- Deferred / averaged / ignored: 0–3

**Actionability (0-10).** Can the author implement the prescriptions today? Each prescription that names a file, a line, a probe, and a pass/fail criterion is +2. Each prescription whose reach is wider than the named file is +1. Each prescription that depends on a design decision not yet made (e.g., "expand the proxy allow-list" without enumerating the new ops) is +0.

**Confidence (0-10).** Self-assessed certainty in the verdict. Honest calibration:
- High (≤1 known gap, all in the "What I could not check" section): 9
- Medium (2–3 gaps): 5
- Low (>3 gaps, or a gap that affects the verdict): 2

The "What I could not check" section is the evidence. A round without one is a 0/10 on confidence.

## Thresholds

- **Ship** ≥ 40/50 with all blocking items closed and no "could not check" gap that affects the verdict.
- **Continue** 30–39/50. Plan the next round with the lenses the score identifies as missing. If the score gap is on Resolution or Verifiability, the next round's plan must include a live measurement, not another read.
- **Redo** < 30/50. The plan that produced this score is wrong. Spawn parallel-agent lens-check (see below) before the next round starts.

## Spawning parallel agents (the lens-check pattern)

When you cannot decide whether the next round's plan has the right lenses — which is most of the time on rounds that introduce new code, new env vars, or new deployment shapes — spawn two parallel agents:

- **Lens inventory** — "identify every distinct lens this round should cover; compare with my plan; recommend minimum / expected-r5 / maximum sets with cost and score projection." Reads the prior adjudication and the diff.
- **Plan attack** — "you are a sceptic of my round-N+1 plan; find what it misses; the failure mode you should hunt is the same defect class the prior round's meta-review caught." Reads the prior adjudication and the orchestrator's plan only.

Both agents use the same model (typically `minimax/MiniMax-M3`) but write to separate output files. The orchestrator reads both, synthesises, decides.

The reason this is two agents and not one: the lens-inventory agent enumerates; the attack agent hunts. An agent doing both will underweight whichever lens the orchestrator's plan already names, because its narrative will lock onto the plan as the centre.

## Distillation — after every round, not at the end

The lessons from each round are inputs to the next round, not to a future skill rewrite. After every round:

1. Read every evidence file (reviews, adjudication, meta-reviews).
2. List every defect the meta-reviews caught the primary passes missed.
3. Categorise: was it a reasoning defect, a prescription defect, a latent defect, a scope defect?
4. For each category, ask: which skill should have caught it? What change to that skill would have caught it?
5. Edit the skill file directly. Each rule needs the case that produced it (per `pi-pilot`'s README convention).
6. Commit the skill change with the PR's evidence as the message body.

`pi-distil` exists because skills that are only ever added to become skills that are not read. Doing the distillation immediately after the round that produced the lesson is what keeps the rules in the skills current with the rounds that paid for them.

## The "What I could not check" discipline

Every evidence file ends with one. The orchestrator's adjudication has one; the meta-reviews have one; the prescription verifier has one. The list is short by design — a long list is the score's tell that the verifier was dutiful, not honest.

Format:

```
## What I could not check

- **I did not run X.** The argument rests on reading Y, not on a measurement.
- **I did not verify Z.** The defect is the right shape, but it is latent until W lands.
- **The reviewer and I share a model.** The three sweeps I ran are reported above; the
  reviewer's agreement is not independent verification.
```

A "What I could not check" section that does not include "The reviewer and I share a model" when that is true is the score's tell that the calibration is off.

## Lens inventory — when to ask for one

A lens inventory is owed when:

- The prior round's score is in the 30–39 range and the gap is on coverage.
- The next round's prescriptions add new code, new env vars, or new deployment shapes.
- The unit's `touches` will expand or has expanded without a `work-split.json` amendment.
- The round-3 meta-review caught a defect class the prior lens set did not catch.

A lens inventory is NOT owed when:

- The prior round shipped at ≥ 40 and the next round is a single-blocker fix.
- The next round is a documentation-only update.

## The model — always `minimax/MiniMax-M3`

Per the project's standard, all PI runs the orchestrator spawns use `--model minimax/MiniMax-M3`. The model string is verified by `pi auth check --provider minimax --model minimax/MiniMax-M3` returning "ready" before the first `pilot.py start --model` call. A bare `--model minimax` is interpreted as a different provider (huggingface) and fails with "No API key found for huggingface"; the correct pattern is `provider/model`, two segments.

When only one model is available, multi-lens passes substitute for multi-model reviews; the round count rises to compensate. When two models are available, the project convention (AGENTS.md) is two reviewers on different models per round; the orchestrator's job is then to keep them apart (different sessions, different briefs, no shared context) and to settle disagreements between them.

## Dual-model parallel review (M3 + M2.7-highspeed)

The orchestrator's standard mode is to spawn **two reviewers on the same brief with different models**: one on `minimax/MiniMax-M3`, one on `minimax/MiniMax-M2.7-highspeed`. The two produce independent samples of the same lens; the orchestrator compares the outputs, settles disagreements, and decides.

### Why two models on the same lens

A single model on a single lens produces one sample. The same lens on a second model produces a second sample. The two samples are not independent if both models share training data or architectural priors, but they are independent enough that the agreement set is high-confidence and the disagreement set is where the orchestrator's attention goes. Three reasons to keep the pair:

- **Coverage.** M3 is the slower, deeper model; M2.7-highspeed is the faster, cheaper model. Spawning both on the same lens catches what M3 catches AND what M2.7-highspeed catches in the same wall-clock.
- **Disagreement mining.** Where M3 and M2.7-highspeed disagree, the disagreement is exactly the "the reviewer's claim was on intent, not on the code" surface. The orchestrator walks the disagreement against the code, settles it, and either accepts the consensus or files the dissent as a finding.
- **Cost calibration.** A model pair that agrees on every finding across multiple rounds is over-budgeted (one model would do). A model pair that disagrees on most findings is misconfigured (the briefs may be unclear). The orchestrator tracks the agreement rate per round and adjusts.

### How to spawn the pair

```sh
# Same brief, two models, two sessions, two PIDs
pilot.py start --unit <unit>-revA-m3 \
  --task <kind> --model minimax/MiniMax-M3 \
  --cwd <dir> --brief <brief-A>.md
pilot.py start --unit <unit>-revA-27hs \
  --task <kind> --model minimax/MiniMax-M2.7-highspeed \
  --cwd <dir> --brief <brief-A>.md
```

The brief is identical for both reviewers; only the model string differs. The orchestrator does not tell the reviewer which model it is running on (the `--model` flag is a launch argument, not part of the brief). Each reviewer's session is independent (no shared context).

### Comparing the outputs

When both reviewers finish, the orchestrator:

1. Reads both reports.
2. Builds a finding-by-finding comparison table: which model caught which defect, where they agree, where they disagree.
3. Settles disagreements by reading the code (the orchestrator's own walk, not by deferring to either reviewer).
4. Files the consensus as the round's findings.
5. Files significant dissents as worth-knowing items ("M3 caught this; M2.7-highspeed missed it" or vice versa).

The agreement rate is itself data. A round where the two models agree on 90%+ of findings is over-budgeted; a round where they agree on 50% needs a closer look at the briefs.

### Verifying the model string

`pi auth check --provider minimax --model minimax/MiniMax-M3` returns "ready". The same for `minimax/MiniMax-M2.7-highspeed`. A bare `--model minimax` is interpreted as a different provider (huggingface) and fails with "No API key found for huggingface"; the correct pattern is `provider/model`, two segments. The full model catalog is in `/home/team/.local/node24/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/providers/data/minimax.json`.

### Per-reviewer output paths (do not collide)

When spawning two reviewers on the same lens with two models, **each reviewer writes to a unique output path** (e.g. `/tmp/w12-r6-revA-m3.md`, `/tmp/w12-r6-revA-27hs.md`). If both write to the same file, the last writer wins and the orchestrator loses the independent reports it needs to compare.

PR #96 W12-r6 spawned 4 reviewers (revA-m3, revA-27hs, revB-m3, revB-27hs) but the brief named only two output paths (`/tmp/w12-r5-reviewer-a.md`, `/tmp/w12-r5-reviewer-b.md`). The M3 and M2.7-highspeed reports overwrote each other; the orchestrator had to reconstruct the comparison from the `pilot.py wait` summaries (which captured the headline but lost the per-finding detail). The fix is in the brief template, not the launch command: each reviewer is given a path that includes its unit suffix.

A template:

```
## Output
Write your findings to `/tmp/<unit>-<lens>-<model>.md` (e.g. `/tmp/w12-r6-revA-m3.md`).
```

The orchestrator verifies the file exists after the run completes; if not, the wait summary is the fallback evidence.

## What you must not do

- **Do not review.** When a subagent's evidence has a defect, the action is to spawn a meta-review, not to fix it yourself. Reading the diff to verify a citation is fine; reading the diff to find new defects is not.
- **Do not average reviewers.** A lone "merge" against two "send back" is a claim to check, not a vote to weigh. Settle by measuring, or name the disagreement unresolved.
- **Do not ship on the author's promise.** "The verifier exits 0" is the verifier being tautological. A "What I could not check" gap on the verifier is a gap on the verdict.
- **Do not skip the "What I could not check" section.** A round without it is a 0 on confidence.

## What you read first

Before planning a round:

1. `pi-pilot` (this skill).
2. The PR's diff (read what the reviews will read).
3. The unit's `work-split.json` (know the `touches` before the lenses).
4. The prior round's adjudication + every meta-review.
5. The project's AGENTS.md and ARCHITECTURE-SPINE.md (know the rules before applying them).

Then write the brief for each parallel reviewer. The brief is the contract: it names the lens, the file to read, the standard to apply, what to write, what not to touch. A reviewer whose brief is a copy of the orchestrator's plan will produce a reviewer that agrees with the plan; you want a reviewer that disagrees where the plan is wrong.

## Confirm the post-fix diff exists before planning

PR #96 W12-r4 was opened with the orchestrator's plan to verify the prescriptions, both reviewers confirmed that the post-fix diff did not exist (`git log <last-commit>..HEAD` returned zero commits), the round produced a precise baseline enumeration rather than a verdict, and the score fell below the continue threshold. The orchestrator's plan was built on an assumption the orchestrator did not verify: that the author had implemented the prescriptions.

Before planning a round that depends on post-fix work, **the orchestrator runs `git log <prior-round-commit>..HEAD` on the PR branch and confirms there are new commits.** If the diff is empty, the round is invalid as planned. Three options:

1. **Cancel the round.** The author's work has not landed; running the round produces a vacuous score and burns model credit. The orchestrator's job is to notice, not to waste reviewers.
2. **Re-purpose the round as a baseline enumeration.** The reviewers' lenses can still produce a precise inventory of what the prescriptions must close (the docker operations the proxy must allow, the env vars the verifier must set, the comments the prescriptions must fix). The output becomes the baseline for the round that runs *after* the author implements. Score the round honestly (low, because no prescriptions to verify) and document the baseline.
3. **Open the round with a different lens set.** If the prescriptions have not landed but the round is still useful, the lens set shifts to "elaborate the prescriptions more precisely" rather than "verify them." The two are different jobs and produce different evidence.

The default is (1) with (2) as the runner-up. (3) is for the rare case where the prescriptions themselves are the round's deliverable, not the implementation.

The principle: the orchestrator's plan must be grounded in evidence, not assumption. Verifying that the diff exists takes one command; running a round on a non-existent diff costs a reviewer.

## When to stop spawning rounds (the author bottleneck)

PR #96 W12-r5 was the second consecutive round that produced a baseline-confirmation verdict (score 29/50, redo) because the post-fix diff was still empty. The orchestrator's instinct was to spawn round 6 with the same lens set, on the assumption that a third pass would either land a verdict or surface a new defect. Neither held: round 6 would produce the same baseline-confirmation finding as rounds 4 and 5.

The orchestrator's job is forward progress. When two consecutive rounds produce the same baseline-confirmation finding, the bottleneck is the author, not the reviews. **The orchestrator stops spawning rounds** and pauses until the author lands work. The resume protocol is `git log <prior-round-commit>..HEAD` again — when the diff is non-empty, the cycle resumes.

Three signals that the bottleneck has shifted from the reviews to the author:

1. **Two consecutive rounds with the same score** and the same headline finding. Different rounds, different reviewers, same score, same headline — the reviewer process is not producing new information.
2. **A round's headline is "the diff is empty."** Once a round's main finding is the absence of the diff, every subsequent round with the same lens set will produce the same finding.
3. **The resume trigger is external.** The orchestrator cannot make the author implement; only the author can. Stopping is not failure; it is the orchestrator recognising the boundary of its authority.

When the orchestrator stops, the action is:

- Document the state honestly (`score.json` with `decision: "stop"` and the resume protocol).
- Update the prior adjudication with the round outcomes (so the next round has a continuous record).
- Tell the user / the operator the pause is deliberate, not a failure.
- Save model credit for the round that will actually land a verdict.

Spawning round 6 anyway, on the basis that "another pass might catch something," is the same anti-pattern as a CI runner that retries on green tests until the budget runs out. The fix is to recognise the bottleneck has moved, not to retry the same loop.
