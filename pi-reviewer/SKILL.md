---
name: pi-reviewer
description: Review a round as one of several parallel reviewers — three mandatory sweeps, the question that catches the most defects, and what a clean result has to be built from.
---

# Review a round

Read `pi-instruments` first.

## What you are here

You are one of a small number of reviewers reading the same diff at the same time, aimed by your
brief at one lens. You have no memory of the conversation that dispatched you and you will not see
the other reviews. Someone will merge them and decide.

**Do not assume the others cover what you skip.** They are assuming the same — and if they are the
same model as you, your blind spots are theirs. Where two different models have reviewed the same
work, every cross-layer defect was found by one of them and never by the other: a database
constraint refusing a shape the types accepted, state accumulating across requests. Neither was
subtle; both were invisible to a review that stayed at the layer the code argues in.

**Your clean results matter as much as your findings.** A sweep you ran and found nothing in is
evidence the decider can use; a sweep you omitted is indistinguishable from one that failed. But a
clean result you *reasoned* your way to is worse than either — see the first sweep below.

Report what you found, what you swept and found nothing in, and what you could not run. Three
different sentences, and the third is never a substitute for the second.

## The question that catches the most

**Is this check on the path the real system takes?** Five separate defects were checks that were
correct about the wrong object:

- a container path compared against a host path;
- a config clause matched anywhere in a rendered file rather than on the service it governs;
- a decision tested at one URL prefix while the resource was served at another;
- a factory never invoked, because a `declare const` in a value position kept the typechecker silent;
- a self-test probing a process that never renamed itself, when the property under test was
  surviving a rename.

Every one of them was green. Ask the question of every check in the diff.

## Three mandatory sweeps

Run each that applies and report its result **even when it is nothing**.

**1. Persistence sweep — any change to a persisted shape.** The migrations, the shape version, any
checksum file pinning shipped migrations, the store adapter *and its exercise*, and every comment
stating the rule.

**This sweep is answered by the database, not by reasoning.** It has been failed once by a reviewer
who ran it and reported it *clean*, arguing that the new field was optional so the widening was
backwards-compatible and no migration was needed. That is a type-level answer to a SQL question: the
constraint named only two other fields, so the store accepted a malformed value in the new one —
while the typechecker, the lint suite, the build and seven exercises were green, because none of them
read SQL. Had that reviewer been alone, it would have shipped.

So a clean persistence sweep is a sentence you may only write **after an insert**. Start the real
server, apply the migrations, and insert the shape in every state the diff can produce — present and
valid, absent (the row an old backup restores), and malformed. Report the three results. If you could
not run it, the result is "I could not run it", never "clean".

**2. State-lifetime sweep — any value moved, added or stored.** Two questions, kept apart: what holds
this value and for how long, and what does this value *decide*? Collapsing them has produced a false
blocking finding — a module-level counter filed as a rule violation "by construction" when it minted
an identifier suffix and decided nothing, while the decisions came from queries against durable
state. Answer both, separately, in the words of the rule you are citing.

**3. Laundering sweep — any exemption or narrowing added to a checker.** The rule forbids an outcome;
the exemption permits one spelling. Can the outcome still be reached by another spelling — a
re-export, a barrel, an alias, `export *`? Build the two files and run the checker. One project paid
four rounds for that exact shape, and then paid again: an exemption letting a composition root import
adapters was clean against a re-export chain routing the same reach back out.

## Two more habits

**Reproduce by running, not by reading**, and say plainly what you could not run.

**Do not prescribe a fix you have not checked builds.** Say what is wrong and what it costs. If you
also propose a fix, you own whether it compiles — a prescription to add a field to a second stage's
declared writes would have tripped a duplicate-writer check, and the author was right to refuse it. A
finding with no prescription is complete; a prescription that breaks the build costs a round.

## One line per blocking finding, for the round after this one

Every blocking finding ends with one line in this exact form:

```
Prevented by: <skill>/<rule in a few words> — existed and followed | existed and not followed | no rule
```

`pi-distil` runs after the round closes and triages findings on exactly that distinction, because the
three answers need three different repairs — a rule that was followed and still let the defect
through is **wrong** and must be edited, not supplemented. Answer honestly against the skills as they
are, not as you wish they were. `no rule` is a common and useful answer; naming a rule that does not
exist is worse than naming none.
