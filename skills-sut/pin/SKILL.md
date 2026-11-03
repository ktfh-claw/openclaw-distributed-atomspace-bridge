---
name: pin
description: >-
  WHY: tool results are gone next cycle — the pinned ledger is the only
  working-memory channel that survives a wake cycle, so task state you
  must not lose between cycles belongs in a pin. WHEN: after EVERY tool
  result, to record the updated task state (step, done-items, and the
  NEXT literal action); at the first cycle of a task, to pin the ledger
  with the next action set; whenever a receipt, count, handle, or
  derivation output is too important to lose. HOW: run via exec:
  python3 skills/pin/pin.py '<text>' — the text is appended as ONE line
  to benchmark/pinned-ledger.md (workspace-relative). Ledger discipline:
  one line per pin in the form LEDGER: step <n> | done: <done-items> |
  next: <the-next-literal-action>; the LAST line is the CURRENT state —
  earlier lines are stale history; when a step completes, advance the
  ledger to the next step in the same pin; pin truthfully — a pin is
  issued only AFTER the action it claims has actually happened, never a
  claim before the work exists. Pinning the same text twice is a no-op.
  Not durable across restarts: for that, write a memory file or persist
  to DAS.
---

# pin — working-memory pinned ledger (exec CLI form)

## Invocation (exec tool)

```
python3 skills/pin/pin.py 'LEDGER: step 2 | done: first fact persisted | next: (add-atom ...)'
```

The text is appended as ONE line to `benchmark/pinned-ledger.md`
(workspace-relative). Pinned items survive wake cycles within the run —
a tool result is gone next cycle, the ledger file is not. To recover
state after a wake cycle, read the ledger.

## Ledger discipline

- One line per pin: `LEDGER: step <n> | done: <done-items> | next: <the
  NEXT literal action, composed from the result you just saw>`.
- The LAST line is the CURRENT state — earlier LEDGER lines are stale.
- When a step completes, advance the ledger to the next step in the
  same pin.
- Pin truthfully: issue a pin only AFTER the action it claims has
  actually happened — never a claim before the write exists. A terminal
  "done" pin lands ONLY after the deliverable write succeeded.
- Pinning the same text twice is a no-op (duplicate of the current last
  line is skipped).
- Not durable across restarts: for that, write a memory file or persist
  to DAS.

## Receipts

- `PIN-OK: benchmark/pinned-ledger.md:<n>` — appended (n = total lines).
- `PIN-OK: duplicate pin (no-op)` — nothing appended (same as last line).
- `PIN-FAILED: <reason>` — the append failed; never claim a pin that
  did not land.

## Environment (set by the deployment)

- `OPENCLAW_SUT_WORKSPACE` — workspace root (the ledger lives at
  `benchmark/pinned-ledger.md` under it).
