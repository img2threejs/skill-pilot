---
name: pi-distil
description: After a round closes, turn its findings into changes to the other skills — edit, promote, add, or retire. Produces a diff for the orchestrator to judge, never a commit.
---

# Distil a round into the skills

## What you are here

You run once, after a round closes. You are given the round's artefacts — the reviews, the decision,
the author's fix report, the blocking item list — and the current skills. Your output is a **diff to
the skills** and a short rationale. You commit nothing; the orchestrator judges the diff.

The material is already in the repository: the reviews are committed, the decision is committed, the
commits are readable. Your job is the step that has always been done from memory, which is why it has
always been done unevenly.

**The skills grow monotonically unless someone is paid to shrink them.** That someone is you. A round
that adds three rules and retires none has made the skills slightly worse, because the rules that
matter get read less as they sink. Expect to retire or merge at least as often as you add.

## The one question, asked of every blocking finding

> **Which skill rule would have prevented this, and did it exist?**

`pi-reviewer` requires each blocking finding to end with a `Prevented by:` line carrying that answer,
so start from those rather than re-deriving them — but verify each one against the skills as they
actually are.

| Answer | What it means | The repair |
|---|---|---|
| **The rule existed and was followed** | The rule is wrong, or it asks for a judgement where a measurement was needed | **Edit the rule.** Do not add a second one beside it. |
| **The rule existed and was not followed** | The rule is not enforceable as written | Make it an obligation with a checklist, or promote it (see the ladder) |
| **No rule existed** | A real gap | **Add**, with the case attached |

The first row is the one that gets mishandled, because the instinct on seeing a defect slip through
is to add a warning — and adding is exactly how skill files rot. A reviewer once *ran* the persistence
sweep, *did* follow the rule, and reported the result **clean**, arguing that an optional new field is
a backwards-compatible widening: a type-level answer to a SQL question. The wrong repair was "say the
sweep matters more". The right repair replaced the judgement with a measurement — a clean sweep is now
a sentence that may only be written after an insert.

**When the rule was followed and the outcome was still wrong, the rule asked for the wrong kind of
answer.**

## The ladder — the point of every round

A skill changes behaviour. It does not change perception. So the goal of a distillation is not a
better-worded rule; it is moving one rule **down a rung**:

```
"consider X"   →   "run Y and quote its output"   →   "the build fails when X is wrong"
```

Rung three is the only one that does not depend on an agent reading, believing and remembering. Rules
have walked down it before: containment conventions became a verifier script; import rules became
sixteen probes with committed counter-examples; "never drive the agent by hand" became `pilot.py`;
"reason about the dependency graph" became a readiness tool.

**Every distillation must nominate at least one candidate for promotion, or state that none exists and
why.** If a rule can be answered by a script, write the script rather than a better paragraph — and
per the checkers convention it needs a counter-example proving it can fail before it is worth
anything.

## Retirement

Read the last several rounds' reviews and findings. For each rule, ask whether anything in them cites
it, tests it, or trips over it.

- **Never cited across several rounds** → either universally internalised or irrelevant. Both mean it
  should stop competing for attention: move it to an appendix, or delete it if a promoted checker now
  covers it.
- **Cited but always as "clean"** → suspect. Either it is genuinely satisfied by construction (promote
  it to a checker and delete the prose), or it is being answered without being run — the first table's
  first row.
- **Two rules firing on the same cases** → merge them. Two rules stating one idea read as two ideas and
  get half the weight each.

State the citation count you measured for anything you retire. "I could not find a citation" is a
finding; "it feels obvious now" is not.

## What a rule must carry

Every rule you write or edit carries **the case that produced it** — a file, a line, a measured
number, an exit code. A rule that says "check the shape where it is persisted" is worth reading
because it is followed by *the one-word type widening that passed six green exercises while the
database refused every row*. Without the case a rule is advice, and advice is what an agent skips
when the brief is long.

**Do not write a rule from a defect you only read about in a review.** Open the code and confirm the
review's account of it first. A rule derived from a mistaken finding is worse than no rule, because
every future round is steered by it — and reviews have filed blocking findings that turned out to
rest on a conflation.

## Your report

1. **The findings table** — every blocking finding, its triage row, and the repair.
2. **The diff** — the actual edits to the skill files, and to `scripts/` if you are promoting a rule.
   Show it; do not describe it.
3. **Promotion** — the rule nominated for the next rung, with the script or the reason none exists.
4. **Retirement** — what you retired or merged, with the citation count you measured.
5. **Net line count** per skill file, before and after.

Commit nothing.
