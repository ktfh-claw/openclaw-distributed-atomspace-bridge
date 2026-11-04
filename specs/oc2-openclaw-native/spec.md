# Spec — oc2-openclaw-native: OpenClaw-native windowless-room harness

Directive: Balázs 2026-11-04 22:54/22:58 UTC (Discord DM, voice brief). Branch:
`oc2-openclaw-native` off origin/main @08006eb (merged oc1 `openclaw-sut-adapter`).
Owner explicitly ABANDONS the comparability constraint with the Omega runs
("do not keep this comparable to the other 10-run series") and refocuses on the
ORIGINAL objective: **a reasoning agent with strict provenance tracking** —
extract knowledge once from the windowless-room source corpus into DAS, then
LATER, in separate agent turns, use that extracted knowledge to answer the
three case questions strictly from the DAS KB with receipts.

## Why (oc1 10-run failure analysis — the driver for every change)

oc1 results (2/10 full GATE PASS, 14/30 case passes, judge TRUE on 21/21 graded
answers): the agent's REASONING was never wrong; every failure class was
memory-channel / harness-mechanics:

1. **Stall-aborts, 9/30** (4 extraction-phase + 5 phase-2): extraction-pace
   variance (persist runs launching 20–25 min after case start), the 15→25-min
   watchdog, and forward-signal blind spots.
2. **Forward-signal blind spot (oc1e RCA)**: persist receipts land in the
   write-bridge SIDECAR (`persist-receipts.log`), NOT in the agent container's
   docker logs; the harness's stall watchdog greps agent-container docker logs
   for `BRIDGE-PERSIST-OK` → a healthy extraction is judged stalled.
3. **Zombie re-dispatch interference**: gateway restart-recovery re-dispatches
   interrupted turns into the NEXT phase's window (oc1a original idle-trap,
   oc1c original manifest landing after deadline, 1 graded case polluted by a
   zombie's dispatch).
4. **Stale-manifest idle-trap (oc1a original)**: the phase-1 hygiene archives
   stale manifests into `knowledge-checkpoints/.archive-pre-<run>/` — INSIDE
   the agent-readable dir; the agent found the archived manifest, followed the
   STOP rule ("manifest already written → do nothing"), and never extracted.
5. **Per-case extraction duplication**: each of the 3 cases re-extracts the
   SAME corpus (3× the stall exposure, 3× the quota burn, and the shared-DB
   state means later cases found receipts "already present" and idled).
6. **Format variance in the answers block**: FACTS: lines carrying inline
   `top=<handle>` annotations (E_NO_FACTS + H_MISMATCH, 2 cases), REASONING
   first step = answer expr instead of the bare query clause
   (R_TRACE_NOT_GROUNDED, 3), degenerate QUERY transcription (2).
7. **Pin-channel overhead**: the `pin` skill existed only because Omega's
   runtime loses tool results across wake cycles. OpenClaw sessions RETAIN
   full conversation context across tool calls and wake cycles — the pinned
   ledger is dead weight, and its prompt discipline consumed turn budget and
   caused close-out churn.

## Required changes (the owner's directive, made concrete)

### C1 — Remove the pin skill completely
- Delete `skills-sut/pin/` from the repo.
- Remove `pin` from `deploy/openclaw-sut/deploy.sh` `SUT_SKILLS`; deploy must
  also REMOVE a stale `/var/openclaw/workspace/skills/pin` from an existing
  deployed SUT workspace (idempotent re-run must not leave the old skill
  installed).
- Harness: remove the pin census lane (`LEDGER_PIN_RE`, `_census_ledger_pins`,
  pin-based `classify_adherence` / `_adherence_lane` inputs). Adherence keeps
  ONLY the answers-file-based `ADHERENCE_DUPLICATE_BLOCK` check; the
  pin-based `ADHERENCE_FALSE_COMPLETION` condition is removed with the pin
  channel (no pin exists to make a false claim with).
- Prompt templates: remove ALL pin/ledger references and the "tool results do
  NOT survive a wake cycle" premise (false for OpenClaw).

### C2 — OpenClaw-native cross-wake memory (replaces pin)
- The ONLY mandated working-memory channels are now: (a) the OpenClaw session's
  own conversation continuity (no action needed — it is the runtime default),
  and (b) the durable workspace artifacts the gate reads: the facts index
  (`benchmark/facts-index.md`), the checkpoint manifest, and `answers.md`.
- The extraction prompt keeps the facts-index discipline (append
  `expr <expression> top=<handle>` after every persist receipt — the gate
  reads this file); the reasoning prompt keeps the answers-block format.
- Do NOT add any new memory mechanism. Do NOT touch gateway config.

### C3 — Shared one-time KB extraction for the 3 cases
- New run structure `full` (--two-phase retained for compat or replaced —
  worker decides, but the DEFAULT `full --agent-profile openclaw` path is the
  new shared-KB flow): preflight → cleanup-das → ONE run-level EXTRACTION
  phase (extract the corpus ONCE, persist, write manifest + facts index) →
  phase-1 log snapshot → then PER CASE (original, unsolvable, false):
  reasoning-phase restart (fresh session) → answer wait → grade → report →
  teardown.
- The extraction prompt no longer carries a single case's question as
  context; it lists ALL THREE case questions as extraction context (the KB
  must be sufficient for all three) and names the corpus sources ONCE.
- Per-case phase-1 hygiene (stale-manifest sweeps) applies only to the
  run-level extraction, ONCE per run.
- Grade/verdict per case unchanged; a run's GATE verdict remains the AND over
  the 3 cases; report.json gains a section recording the shared extraction
  (manifest, receipts count, elapsed).

### C4 — Stale-manifest archive OUT of the agent-readable dir
- Archive pre-existing manifests to a harness-side path OUTSIDE the agent
  workspace (e.g. `results/<run-id>/archive-manifests/` on the host), never
  under the memory volume's `knowledge-checkpoints/`.

### C5 — Forward-signal census fix (oc1e RCA)
- The stall-watchdog persist-receipt forward signal must read the write-bridge
  sidecar receipts lane (`persist-receipts.log` via the write-bridge
  container's workspace volume, or the write-bridge docker logs — whichever
  the deployed bridge actually writes; inspect `deploy/das/write-bridge/` to
  determine the authoritative lane and use it), in ADDITION to (not instead
  of) the agent-container docker-log grep.

### C6 — Per-phase session identity (zombie isolation)
- Each delivered turn (run-level extraction, per-case reasoning) targets its
  OWN session id (e.g. `wr-<run-id>-extract`, `wr-<run-id>-case-<case>`), so
  gateway restart-recovery cannot re-dispatch a stale phase's zombie into the
  live phase's session. Inspect `_delivery_command` for how the OpenClaw
  profile names its sessions today and namespace per phase; keep the
  readiness-wait (R-A2) and re-issue machinery unchanged.

### C7 — Prompt tightening (prompt-side only, gates untouched)
- Extraction prompt: bounded single-pass, no duplicate persists (dedupe by
  recorded expr), STOP rule tied to manifest write only.
- Reasoning prompt: keep the answers-block grammar EXACTLY (QUERY /
  DAS_RETRIEVE_OK / FACTS / HANDLES / REASONING / FINAL ANSWER), and keep the
  FACTS `top=<handle>` warning (oc1b lesson: copy BARE expressions from the
  record into FACTS:, never the `expr … top=` record line) and the
  REASONING first-step warning (first step = the bare query clause with $X,
  no stv, no extra paren layer — oc1d lesson).

## Frozen (byte-identical vs base 08006eb; diff must be empty)

- `tests/reasoning-windowless-room/grading.py`, `facts.py`,
  `provenance_check.py`, `history_parse.py`, `llm_judge.py`,
  `test-spec.md`, `GATES-REFERENCE.md`, `background/**`
- `deploy/das/**` (the DAS write-bridge / read-proxy / atomdb deployment)
- `deploy/openclaw-sut/Dockerfile.sut`, `docker-compose.yml`,
  `openclaw-sut.service`, `metta-libs/**` (runtime pins stay frozen)

Gate semantics: the A/Q/E/R/P/H verdict composition and every condition code
are unchanged. The ONLY semantic deletions are the pin-derived adherence
conditions (with the pin channel gone) — owner-approved.

## Explicitly NOT in scope

- No new memory/persistence mechanism for saved facts (owner: "keep these
  facts marked down for now" — the facts-index + manifest + DAS status quo
  stands).
- No relaxation of any gate other than the pin-derived ones listed above.
- No upstream OpenClaw or DAS code changes. No gateway-config changes.
- No touching the Omega series artifacts (`historical/`, oc1 results).

## Acceptance criteria

1. `grep -rn "pin" skills-sut/ deploy/openclaw-sut/ tests/reasoning-windowless-room/*.py`
   returns no live pin references (historical docs/specs excluded); the pin
   skill directory is deleted; deploy.sh removes a stale deployed pin dir.
2. `git diff 08006eb -- <frozen list>` is empty.
3. Unit suite green: `tests/reasoning-windowless-room/unit/run_tests.py` —
   updated for the shared-KB flow and pin removal; every removed behavior has
   its test deleted or rewritten, every new behavior has a test.
4. New/updated unit tests cover: shared-extraction sequencing (extraction
   once, three reasoning cases), stale-manifest archive path outside the
   agent workspace, forward-signal sidecar lane, per-phase session naming,
   adherence lane without pins (duplicate-block check retained).
5. Diff SHAPE matches the directive: net deletions of pin machinery and
   per-case extraction duplication; prompt templates SHORTER than the oc1
   versions (word-count must not grow).
6. Orchestrator-side (NOT worker): rsync to OVH, idempotent deploy.sh re-run,
   smoke run of the new harness, then the oc2 10-run series + stats report.

## Stop-and-ask

- If any frozen file appears to need a change to implement C1–C7 → stop and
  report instead of editing it.
- If the OpenClaw delivery CLI cannot target per-phase session ids → report
  the exact CLI surface found instead of inventing a workaround.
- If the write-bridge receipts lane cannot be read harness-side → report
  evidence and propose alternatives instead of guessing.
