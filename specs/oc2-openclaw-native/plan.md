# Plan — oc2-openclaw-native

Phases 1–4 are worker-owned (coder-opencode, branch `oc2-openclaw-native`
off 08006eb). Phase 5+ is orchestrator-owned (deploy/smoke/series — never
the worker).

## Phase 1 — Recon + pin removal (C1)
- Read `run_benchmark.py` fully; map every pin reference (census lane,
  `classify_adherence`, preflight skill list, prompt templates).
- Delete `skills-sut/pin/`; remove `pin` from `deploy.sh SUT_SKILLS`; add
  idempotent removal of a stale deployed `skills/pin` in deploy stage 6 (or
  the equivalent skill-install stage — inspect deploy.sh first).
- Remove pin/ledger references from both prompt templates; keep facts-index
  discipline and answers-block grammar (C2/C7).
- Adherence lane: keep `ADHERENCE_DUPLICATE_BLOCK`; delete the
  pin-derived `ADHERENCE_FALSE_COMPLETION` path. Update the L1/watchdog unit
  tests accordingly.
- Commit + push.

## Phase 2 — Shared one-time extraction (C3) + zombie isolation (C6) + archive fix (C4)
- New run flow: preflight → cleanup-das → run-level extraction → phase-1 log
  snapshot → per-case reasoning restart/answer/grade → report (with a
  shared-extraction section) → teardown. Keep `--cases` iteration filter
  working for the reasoning cases.
- Extraction prompt: corpus context for ALL THREE case questions, no per-case
  question framing; STOP rule tied to manifest write.
- Session ids per phase: inspect `_delivery_command` (OpenClaw profile);
  namespace extraction vs per-case reasoning sessions (`wr-<run>-extract`,
  `wr-<run>-case-<case>`); keep R-A2 readiness wait + re-issue machinery.
- Stale-manifest archive → `results/<run-id>/archive-manifests/` (host-side,
  outside the memory volume); never inside agent-readable
  `knowledge-checkpoints/`.
- Commit + push.

## Phase 3 — Forward-signal census fix (C5)
- Inspect `deploy/das/write-bridge/` to determine where
  `BRIDGE-PERSIST-OK` receipts durably land (sidecar `persist-receipts.log`
  lane vs write-bridge docker logs). Make the stall-watchdog forward signal
  read that lane in addition to the agent-container docker-log grep.
- Unit test with a fixture receipt line for the new lane.
- Commit + push.

## Phase 4 — Tests + docs + final shape check
- Update/extend `unit/run_tests.py` suite: shared-KB sequencing, archive
  path, sidecar lane, session naming, pin-free adherence, prompt-render
  tests for the new templates (word-count must not grow vs oc1 templates —
  assert it in the render test).
- Full suite green; `git diff 08006eb -- <frozen list>` empty (assert in the
  report, not trusted to memory).
- Update `tests/reasoning-windowless-room/README.md` + `deploy/openclaw-sut/README.md`
  for the new flow (no pin skill; shared extraction).
- Final report: commits, test summary, `git diff 08006eb --stat`, frozen-file
  proof, design decisions, deviations.

## Phase 5 — orchestrator (NOT the worker)
- Review diff line-by-line; rerun suite locally; verify frozen files.
- rsync to OVH (no --delete over runtime.env), idempotent deploy.sh re-run.
- Smoke: one full new-flow run (extraction once + 3 reasoning cases).
- RCA+fix+retest on invalid executions; then the oc2 10-run series + GDoc
  stats report + cron close-out.

## Open design decisions (worker may choose, must report)
- Whether `--two-phase` stays as a compat alias or is removed (default full =
  new flow).
- Sidecar lane read mechanism (volume path vs write-bridge docker logs) —
  pick whichever the deployed bridge actually writes, evidence in report.
- Exact session-id scheme, as long as extraction and each case are distinct
  sessions.
