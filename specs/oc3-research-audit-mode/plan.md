# Plan — Research Q&A audit mode

Sequenced implementation, all on `oc3-reasoning-battery`, additive only.

## Phases

1. **P1 — Question packs (R2):** pack loader/validator (`question-pack/1`
   schema) in a new module; `--battery` accepts built-in id `battery` OR a
   filesystem path; collision guard vs frozen TEST_CASES ids; unit tests
   (valid load, each rejection branch, built-in id compat).
2. **P2 — Faithfulness judge (R3):** new judge prompt template; selection
   seam in run_benchmark.py where judge_fn is wired (case has no
   expected_answer → faithfulness); existing judge untouched for
   expected-answer cases; unit tests for both selection paths.
3. **P3 — Live-retrieve contract (R1):** battery prompt template gains the
   mandatory retrieve-before-FACTS instruction; standard prompts untouched;
   unit test asserts rendered battery prompt content.
4. **P4 — End-to-end battery grading on fixtures + docs:** full battery-mode
   grading pass over a fixture pack in unit tests (no live infra); README +
   test-spec sections; full suite green.

## Constraints (frozen)

grading.py, history_parse.py, provenance_check.py, llm_judge.py,
background/, prompts/{original,false-statement,unsolvable,expected-answer}*.md,
standard 3-case full path — all byte-identical. No OVH testing (oc3 series
live). Commits incremental, `oc3 audit:` prefixed.

## Verification

Unit suite green (494 + new); `git diff main...HEAD -- <frozen paths>` empty
except facts.py additions; rendered-prompt and selection-path assertions; docs
updated.
