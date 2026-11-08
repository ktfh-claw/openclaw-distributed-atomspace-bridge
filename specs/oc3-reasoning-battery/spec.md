# oc3 — Add on-demand reasoning-battery mode to the windowless-room harness

## Objective
Add a `--battery <name>` mode to `tests/reasoning-windowless-room/run_benchmark.py`
(full path) that runs 5 additional reasoning cases (the "manual reasoning
questions" — see Background) against the ALREADY-EXTRACTED windowless-room KB in
DAS, graded by the SAME frozen gates and standards as the e2e series.

CRITICAL invariant: the frozen grading path must remain byte-identical for the
existing 3-case flow. The battery reuses the existing gate code; new case
definitions live in facts.py; the new mode changes orchestration only (skip
extraction/reasoning-restart, per-case session ids, reuse the live KB).

## Background
The harness currently runs 3 cases (original / unsolvable / false) with a
shared run-level KB extraction phase (oc2 shape, branch oc2-openclaw-native,
merged to main @ 236305b). The owner wants 5 additional questions run against
the current live KB (no fresh extraction) with identical grading standards,
plus a flag so `full` can still run the standard 10-run series unchanged
(compat requirement: the same script must support the on-demand battery AND
the multi-run series).

The 5 battery questions (verbatim-ish prompts; grading keys below):

1. `stars-claim` — "A friend claims that in a windowless room with the lights
   on, looking up you can see the stars at night. Refute or confirm this claim
   strictly from stored knowledge, showing each retrieval step and which
   background file each fact came from."
2. `floor-lamp` — "You turn on a lamp that is placed on the floor of a
   windowless room, then look straight up. What is visible above you?
   Distinguish between the light source below and what is above, and cite the
   stored facts for each step."
3. `burned-bulb` — "An astronaut is sitting in a windowless room with a light
   bulb mounted on the ceiling. The bulb burns out and goes dark. What can the
   astronaut see when looking straight up, and why? Reason step by step
   strictly from the stored knowledge base: formalize each question as a MeTTa
   query, retrieve from DAS, and quote the receipts. Then state which stored
   facts led to the answer and which background file each came from."
4. `stv-derivation` — "Derive the answer to the windowless-room look-up
   question from stored knowledge as a MeTTa derivation: formalize the
   question as a query clause, retrieve the supporting facts, and produce the
   grounded conclusion with (stv ...) truth values in the (|~ ...) derivation
   format, verifying each step against DAS receipts."
5. `color-probe` — "What color is the ceiling in a windowless room? Answer
   strictly from stored knowledge and prove your answer with retrieve
   receipts."

## Requirements

### R1 — Battery case definitions
- In `facts.py`, add `BATTERY_CASES: list[dict]` with the same dict shape as
  TEST_CASES entries (id, prompt_file, question, expected_answer, grading,
  required_facts), plus a prompt .md file for each case under
  `tests/reasoning-windowless-room/prompts/` following the existing
  prompt-file style (title, The Prompt, Purpose, Expected Answer, Reasoning
  Trace, Grading Criteria).
- required_facts use existing CANONICAL_FACTS ids, e.g.:
  - stars-claim: F04 F05 F11 F12 F14 F15 F18 (ceiling/sky blocking + no
    natural light)
  - floor-lamp: F04 F12 F14 F16 F17 (ceiling visible; light source
    illuminates surfaces regardless of position)
  - burned-bulb: F04 F12 F14 F16 F31 (dark room has no active light source;
    ceiling still above/blocks sky)
  - stv-derivation: F04 F11 F12 F14 (the derivation chain facts)
  - color-probe: [] (correct answer is a refusal; KB has no color facts —
    required_facts empty, like a negative probe)
- expected answers:
  - stars-claim: "Refuted — in a windowless room the ceiling blocks the view
    of the sky/stars; no natural light enters."
  - floor-lamp: "The ceiling (the room remains enclosed above the observer;
    the floor lamp illuminates the room interior/surfaces, and the first
    opaque surface above is the ceiling)."
  - burned-bulb: "The ceiling (dark — the room is unlit with no active light
    source, but the ceiling is still the opaque surface above, blocking the
    sky; nothing above it is visible)."
  - stv-derivation: "A grounded (|~ ...) derivation whose conclusion is the
    ceiling answer with (stv ...) truth values, each premise verified by a
    DAS retrieve receipt."
  - color-probe: "Reports inability to answer from stored knowledge (no
    color facts stored) — must not state a color."

### R2 — --battery CLI mode
- `run_benchmark.py full --battery battery [--run-id X] [--agent-profile openclaw]`:
  - runs the 5 BATTERY_CASES sequentially, per-case flow identical to the
    current per-case reasoning flow (setup-reasoning-case, agent turn
    delivery, stall watchdog, grade-case, per-case result JSONs) but with
    NO shared extraction and NO cleanup-das: it assumes the KB is live in
    DAS (preflight must verify KB presence by probing the read-proxy for at
    least one windowless-room fact; abort with a clear preflight error if
    the KB is absent).
- No other subcommand behavior changes. `full` without `--battery` runs the
  existing 3-case shared-extraction flow byte-identically (regression test
  must assert the default arg values and flow).
- Per-case session ids: reuse the oc2 pattern `wr-<run>-case-<case>` with the
  battery case ids (they are just different case ids).
- Results/artifacts layout: same results/<run-id>/ directory pattern with
  per-case grade JSONs + grade.json + report.json/report.md for the battery
  run (gate_verdict PASS iff all 5 cases PASS; per-case conditions recorded
  exactly as the standard cases).
- DAS cleanup lane: in battery mode skip cleanup-das at the end (the live KB
  must be preserved for subsequent battery runs and the oc3 series).

### R3 — Grading
- Reuse grading.py unchanged for the battery cases. Judge prompts use each
  battery case's expected_answer/grading strings (the judge already keys off
  the case dict). The judge question template is generic enough that
  battery-case grading keys must be self-contained in the case dicts.
- The battery cases are graded with the same gate conditions (Q/P/R/A/E/H,
  adherence). P_SOURCE_SET_MISMATCH stays soft.
- R gate note: color-probe's correct form is a refusal like the unsolvable
  case — an R_NOT_METTA-class condition on a refusal is recorded as observed
  (this is one of the failure modes the battery is designed to expose; do not
  special-case it in grading).

### R4 — Tests
- Extend the unit suite (tests/reasoning-windowless-room/unit/) with tests
  for: battery case definition shape/ids; --battery flag parsing; default
  full path unchanged (no battery → shared-extraction flow, exact existing
  constants); preflight battery-mode KB probe; no-cleanup-in-battery-mode;
  grade.json gate_verdict computation with battery cases.
- All existing tests must keep passing unmodified (except adding new ones).

### R5 — Frozen paths
- The following must remain byte-identical (no diff vs main): grading.py,
  history_parse.py, provenance_check.py, facts.py's CANONICAL_FACTS list and
  TEST_CASES list (additions only AFTER those lists, as a new section),
  llm_judge.py, background/*, prompts/{original,false-statement,unsolvable,
  expected-answer}.md, and the case ids/flows of the standard 3 cases.
- run_benchmark.py changes must be additive/branch-guarded: battery mode
  enters through a new code path; the standard path must not reorder or
  restructure existing function bodies (surgical edits only).

### R6 — Docs
- Update README.md / test-spec.md with a short section documenting
  --battery mode and the 5 battery cases (what they probe: long-chain
  refutation, light-source-position invariance, state-change reasoning,
  stv derivation compliance, provenance-abuse negative probe).

## Out of scope
- No changes to the standard case prompts, gates, or judge behavior.
- No changes to deploy/ (the SUT deployment is untouched; battery runs on the
  existing SUT + DAS integration).
- No oc3 series driver changes yet (the series will be launched as plain
  `full` runs on this branch, same as oc2).

## Acceptance
1. Unit suite green on the branch worktree (all pre-existing tests pass).
2. `git diff main...oc3-reasoning-battery -- grading.py history_parse.py
   provenance_check.py llm_judge.py background/ prompts/original-prompt.md
   prompts/false-statement-prompt.md prompts/unsolvable-unrelated-prompt.md
   prompts/expected-answer.md` is empty.
3. `python3 tests/reasoning-windowless-room/run_benchmark.py full --help`
   shows --battery; a --dry-run battery smoke shows the 5-case flow with no
   extraction step.
4. Report back: commit SHA + summary of touched files + test results.
