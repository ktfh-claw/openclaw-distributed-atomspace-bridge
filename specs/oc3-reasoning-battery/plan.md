# oc3 — Plan

Base: main @ d318a06 (clean). Branch: oc3-reasoning-battery (spec @ 3391126).

## Phases
- P1 — facts.py additions: BATTERY_CASES list (5 cases, dict shape identical to
  TEST_CASES), required prompt files (5 new .md under prompts/), placed strictly
  AFTER the existing lists; no byte change to CANONICAL_FACTS / TEST_CASES /
  SOURCE_URLS.
- P2 — run_benchmark.py --battery mode: CLI flag on `full`, battery flow =
  preflight (with live-KB probe; no extraction, no cleanup-das), then per-case
  (setup-reasoning-case → agent turn → stall watchdog → grade-case) for the 5
  battery cases, results under results/<run-id>/, gate.json/report identical
  shape. Standard path untouched (branch-guarded, surgical).
- P3 — tests: unit tests for case-def shape, flag parsing, default-flow
  unchanged, preflight KB probe, no-cleanup, gate_verdict computation; run full
  existing unit suite green.
- P4 — docs (README/test-spec section for --battery), final shape check,
  incremental commits per phase, push after each phase.

## Open design decisions (resolved in spec)
- Battery reuses the live KB; preflight aborts if KB absent (no auto-extract).
- color-probe required_facts = [] (negative probe; refusal is the correct answer).
- R_NOT_METTA on refusals is recorded as observed (the battery exists to expose
  this class) — no grading special case.

## Stop-and-ask conditions
- If the per-case flow in run_benchmark.py cannot be reused without reordering/
  restructuring existing functions (i.e. battery mode requires refactors that
  would touch the standard path), STOP and report the required refactor instead.
- If grading.py's judge/gate code needs ANY change to grade the new cases, STOP
  and report (gates are frozen).
