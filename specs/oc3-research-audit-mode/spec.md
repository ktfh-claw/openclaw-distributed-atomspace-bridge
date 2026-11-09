# Spec: Research Q&A audit mode (oc3-reasoning-battery, additive)

## Context

The oc3 battery run (oc3-battery-20261109a, 2026-11-09) proved the harness's
audit lanes work end-to-end and caught a real provenance failure: with the KB
resident in the agent's workspace, the agent answered correctly but performed
ZERO live das-retrieve calls, quoting receipts copied from the oc2j extraction
record. Gates fired correctly (blocking Q_NOT_IN_HISTORY; judge TRUE 5/5).

Owner directive 2026-11-09 16:52 UTC: implement three changes so the same
e2e harness can also audit REAL research tasks (agents build a KB; later,
arbitrary questions are asked and the answers must be proven grounded in that
DAS KB), while keeping the windowless-room 3-case benchmark byte-identical.

Parent branch: `oc3-reasoning-battery` (battery mode @ 022dea3). All work is
additive on the same branch. The oc3 10-run series on OVH is LIVE — no
infrastructure testing until it terminates; unit tests only.

## Requirements

### R1 — Mandatory live-retrieve contract (battery mode, prompt-level)

Battery prompts must instruct the agent to perform a LIVE das-retrieve for its
QUERY against DAS in the case window BEFORE writing FACTS, and to quote the
receipt from that live call. Rationale: without it, the agent answers from
workspace memory with copied receipts and the Q-gate correctly fails the run
(oc3-battery-20261109a finding). With it, Q_NOT_IN_HISTORY discriminates real
provenance failures instead of recording the memory-answer mode universally.

- Change is in the battery prompt template only (prompts/battery-*.md or the
  template that renders them) — gates and frozen files untouched.
- Standard 3-case flow prompts unchanged (they already have the QUERY-first
  contract).
- The retrieve must target the read-proxy endpoint the agent already uses.

### R2 — External question packs

`full --battery` currently accepts only the built-in pack id `battery`
(BATTERY_CASES in facts.py). Extend so `--battery <pack>` accepts BOTH:

1. built-in id `battery` (existing behavior, byte-compatible), and
2. a filesystem path to a question-pack JSON file.

Pack schema (versioned, `"schema": "question-pack/1"`):

```json
{
  "schema": "question-pack/1",
  "name": "optional human name",
  "cases": [
    {
      "id": "kebab-case-unique",
      "question": "the question text",
      "prompt": "optional full prompt text override",
      "required_facts": ["optional normalized MeTTa expressions"],
      "expected_answer": "optional expected answer for substance judging",
      "source_expectations": ["optional source refs the agent must cite"]
    }
  ]
}
```

- required_facts / expected_answer / source_expectations are all optional;
  an absent expected_answer selects the faithfulness judge (R3).
- Pack validation: unique ids, non-empty question, schema field present;
  clear error on invalid packs; refuse case ids that collide with the frozen
  TEST_CASES ids.
- No cleanup-das and no extraction for external packs either — live-KB reuse,
  same as the built-in battery.

### R3 — Faithfulness judge mode (expected-answer-optional judging)

Today the A-gate judge checks substance against the case's expected answer.
For real research questions there is no ground truth. Add a faithfulness
judge variant selected when the case has no expected_answer:

- Judge question becomes: "Given ONLY the facts the agent presented
  (FACTS/REASONING/its answer text), is the final answer strictly supported
  by those facts — i.e., does the answer follow from the presented evidence
  without inventing facts that are not in the presented set?"
- Judge verdict TRUE = faithful answer (A-substance pass); verdict FALSE =
  the answer overreaches its evidence.
- The judge PROMPT is a new template; llm_judge.py's calling convention and
  grading.py are untouched. Selection happens where the case dict is built /
  judge_fn is wired in run_benchmark.py (non-frozen seam).
- Cases WITH expected_answer keep the existing judge semantics exactly.

## Non-goals

- No gate changes: grading.py, condition codes, history_parse.py,
  provenance_check.py, llm_judge.py, background/ remain byte-identical.
- No changes to the standard 3-case full path behavior.
- No OVH/infrastructure testing until the oc3 series terminates.
- No re-extraction/cleanup for battery packs.

## Acceptance

1. Full unit suite green (existing 494 + new tests).
2. Standard 3-case flow code paths byte-identical (diff shows only
   battery/pack additions and the judge-selection seam).
3. R1: battery prompt renders the live-retrieve contract; unit test asserts
   the rendered prompt contains the retrieve-before-FACTS instruction.
4. R2: external pack JSON loads, validates (good + reject cases), unit test
   drives a full battery-mode grading pass on fixtures; built-in id `battery`
   unchanged.
5. R3: faithfulness judge selected for expected-answer-less cases; existing
   judge selected otherwise; unit test covers both selection paths.
6. Docs: README/test-spec sections updated for packs + faithfulness mode.
