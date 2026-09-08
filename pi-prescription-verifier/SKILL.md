---
name: pi-prescription-verifier
description: After the author implements an adjudication's prescriptions, walk the post-fix diff against each prescription. Four fix shapes (configuration, code, comment, verifier) get four sub-actions. You verify the implementation; you do not review the original defect.
---

# Verify prescriptions after the author implements them

Read `pi-reviewer` first. That skill reviews a diff against a brief; this one verifies the diff *against an adjudication's prescriptions*.

## What you are here

The adjudication named prescriptions for each blocker. The author implemented them. Your job is to confirm each prescription closes the defect the adjudication named, and to catch the failure modes that have cost rounds:

- **A prescription accepted on intent, never re-walked against the code.** The first PR #96 adjudication accepted Lens A's "Tecnativa-style docker socket proxy" allow-list of four operations without walking the containment adapter; the attack meta-reviewer caught the allow-list was actually six operations. The second attack pass caught a further four (the create path) that neither of the first two passes had walked.
- **A prescription whose verifier change is missing or wrong.** The first PR #96 adjudication said "the verify script sets both flags; no change to the verifier is needed"; the attack meta-reviewer caught the verify script set only one of the two flags.
- **A comment rewrite that is itself wrong.** The first PR #96 reviewer's item 11 caught `main.ts:19` referencing a file (`build.sh`) that does not exist. A comment-fix prescription can introduce the same defect class.
- **A scope expansion the unit's `touches` does not cover.** PR #96 W12's `touches` does not include `deploy/studio/**`; the prescriptions added files to that subtree. The scope question is a work-split edit, not a PR comment.

You are not re-reviewing the diff. You are confirming each prescription closed its named defect, in the order the adjudication filed them, with the four fix shapes named explicitly.

## What to read (in this order)

1. `pi-reviewer` (this skill's conventions).
2. The adjudication under verification. The fix-per-item list is your contract.
3. The author's commits since the adjudication (the post-fix diff).
4. The unit's `work-split.json` (for the `touches` check).
5. The relevant files end-to-end — every call site the prescription claims to fix.

## The four fix shapes — four sub-actions

A prescription falls into one or more of these four shapes. Run each shape's sub-action against every prescription.

### Sub-action A — Configuration (env vars, defaults, mounts)

What it covers: env-var reads, default values, mount points, configuration override paths.

Walk:
- The new env-var read in code (`grep -n` for the var name).
- The default value used when the env var is absent.
- The compose file's `environment:` block.
- The Dockerfile's `ENV` directives (if any).
- The verifier's env-var export.
- Every caller of the configuration override path.

Catch:
- Default value does not match the compose mount point (item 12, PR #96: `grantDirectory = '/var/img2/grants'` vs mount `/var/lib/img2/grants`).
- Env var declared but unread (item 6, PR #96: `IMG2_SCRATCH_ROOT`).
- Configuration override path bypasses the new check.
- Mount point created by Dockerfile but not declared by compose.

Confidence calibration: a configuration prescription is verified by reading the code paths and matching them to the deployment shape. A live run is not required.

### Sub-action B — Code (call sites, runtime behaviour)

What it covers: any change to a function body, control flow, new throw, new branch.

Walk:
- Every call site of the modified function.
- The handler or function the prescription claims to change.
- The lifecycle of any value the prescription introduces (where it is read, where it is written, when it is reset).

Catch:
- Allow-list covers the example but not the rule (PR #96 round-3 H1: 4-op allow-list vs 6-op call sites; round-3 attack M1: 6-op allow-list vs 10-op call sites when the create path is included).
- Allow-list does not cover the *next* unit's path (the create path is the next unit's reconciliation path).
- New throw is in the wrong scope (inside `compose()` rather than before it, so the studio does work before refusing).
- Counter / state introduced without a sweep.

Confidence calibration: a code prescription is verified by reading the call sites end-to-end. A live run against a real store / daemon / runtime is preferred where the prescription's reach is to the runtime.

### Sub-action C — Comment / prose / documentation

What it covers: any change to a comment block, README, header docstring, or any other prose claim about the code.

Walk:
- Every prose claim in the post-fix diff.
- The behaviour the prose claims (read the code, do not trust the prose).
- Other prose claims in the same file that *also* describe the behaviour (the comment fix can make a sibling comment drift).

Catch:
- Comment claims behaviour the code does not have (item 9, PR #96: "the capture adapter reads at the type level").
- Comment references a file that does not exist (item 11, PR #96: `build.sh`).
- Comment fix does not address the defect (the comment was rewritten to match the reviewer's prescription, but the prescription itself was wrong — re-walk against the code).
- Sibling comment now drifts (PR #96 item 9's fix did not affect item 10, which is a separate claim in the same Dockerfile).

Confidence calibration: a comment prescription is verified by reading the post-fix comment against the post-fix code. A diff reader can see the comment text; cannot see whether the text is right unless they also read the code the comment describes.

### Sub-action D — Verifier / probe / test

What it covers: any change to a verifier script, a probe, a test fixture, or any script that asserts a behaviour.

Walk:
- The new probe / assertion.
- The setup the probe commits (rows inserted, flags set, processes started).
- The teardown.
- The failure half (the part that asserts the violation is caught).
- The pass half (the part that asserts the bypass / happy path still works).
- Every env var the probe reads and every env var the verifier exports.

Catch:
- Verifier does not set the env var the prescription requires (PR #96 H2: `IMG2_DEPLOYMENT_KIND=smoke-test` not set anywhere in `verify-studio.sh`).
- Probe asserts success but does not assert failure (the Checkers-convention violation).
- Probe's setup is wrong (the violation is not actually committed, so the probe passes by accident).
- Probe's pass-half always passes because the bypass flags are already set in the harness environment.
- Probe is tautological (the verifier runs the probe and asserts the verifier's own output).

Confidence calibration: a verifier prescription is verified by running the verifier end-to-end and observing the exit code AND the assertion messages, not by reading the script. Reading the script is the minimum; running it is the standard.

## The Checkers-convention sweep

Every new check in the post-fix diff must have a committed probe that has been seen failing. A probe is **not** verified by reading the probe; it is verified by:

1. Running the probe with the setup the probe commits.
2. Asserting the probe fails when the violation is committed (failure-half).
3. Asserting the probe passes when the bypass / happy path is exercised (pass-half).
4. Running the probe's setup deliberately broken (wrong column name, missing row, wrong env var) and asserting the probe fails (so the probe cannot be silently passing).

If any of these four is missing, file as a Checkers-convention defect.

## The scope check

Read `work-split.json` for the unit's `touches`. For every file the post-fix diff adds or edits:

- Is the file inside the unit's `touches`?
- If not, is the `work-split.json` amended in the same PR? (AGENTS.md says scope changes go through `work-split.json` first.)
- If neither, the prescription expands the unit's scope without disclosure; file as a scope defect.

A scope expansion that lands inside the unit's existing `touches` is fine. A scope expansion that lands outside and is not disclosed is blocking — the next unit may overlap, or the work-split may already cover this surface through another owner.

## The "What I could not check" section

Every prescription-verifier report ends with one. The list is short by design. A long list is the score's tell.

Items you should always include when true:
- **The reviewer and I share a model.** If true, the agreement between your walk and the adjudication's prescription is not independent verification.
- **I did not run the verifier.** If true, the verifier-only sub-action's confidence is lower; say so.
- **I did not run the proposed runtime (proxy / daemon / store).** If true, the code sub-action's confidence is lower for prescriptions whose reach is to the runtime.
- **I did not see the post-fix diff land in CI.** If true, the verifier-vs-CI-env-divergence gap is open.

## Output

Write your findings to a file the orchestrator names (typically `<evidence-dir>/review-prescription-verifier.md`). Structure:

1. **Headline.** Verdict per prescription: closes / partially-closes / does-not-close / introduces-new.
2. **Sub-action findings.** One section per fix shape that caught a defect.
3. **Checkers-convention findings.** Per probe, with the four-step evidence.
4. **Scope findings.** Per file outside `touches`.
5. **New defects introduced.** Anything the post-fix diff adds that was not in the adjudication's prescription set.
6. **What I could not check.**

## What you must not do

- **Do not re-review the original diff.** The original review is done; the adjudication is done; the author has implemented. Your lens starts at "the prescription was filed; did the implementation close the defect?"
- **Do not propose new prescriptions.** If the post-fix diff introduces a new gap (e.g., a comment-fix prescription that should have included a sibling comment), file it as a finding, do not write the fix.
- **Do not trust the verifier.** The verifier exiting 0 is the verifier being tautological, which is the documented failure mode. Run the verifier, read the assertions, observe the messages, and verify against the harness environment.

## What you read first

Before walking prescriptions:

1. `pi-reviewer` (the conventions: three sweeps, every claim against the code, "What I could not check").
2. The adjudication under verification (the fix-per-item list is your contract).
3. The unit's `work-split.json` (for the `touches` check).
4. The post-fix diff (the author's commits since the adjudication).

Then walk each prescription against the four fix shapes, in order. The four shapes are not parallel; they are sequential. A prescription that has both a configuration change and a verifier change needs both sub-actions in sequence.
