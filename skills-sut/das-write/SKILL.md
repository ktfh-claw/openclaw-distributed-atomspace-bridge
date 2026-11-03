---
name: das-write
description: >-
  WHY: durable knowledge must be persisted to DAS, your persistent
  knowledge store — a fact is justified ONLY by a BRIDGE-PERSIST-OK
  receipt, never by parametric memory. WHEN: call it FIRST whenever a
  task requires persisting a fact, an expression, or knowledge to DAS —
  every durable write goes through this skill. HOW: run via exec:
  python3 skills/das-write/das_write_bridge.py '(metta "(add-atom
  &persistent (<expression>) \"<source-url>\" (stv 0.9 0.8))")' — the
  invocation form maps the (metta "(add-atom ...)") call to this script.
  The add-atom form is (add-atom &persistent <expr> "<http(s)-url |
  abs-container-path>" [(stv s c)]) — you pass ONLY the source
  reference; the bridge fetches or reads the source, hashes it (sha256),
  appends (ref, sha256) to the source ledger, and performs the gated,
  verified DAS write. Success is ONLY the receipt
  BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)] — top=<handle>
  is the fact's top-link atom handle; copy it verbatim, it identifies
  the stored atom. A source reference is REQUIRED on persistent writes —
  append the source URL or an allowed absolute path after the
  expression. There is no agent-side git citation: archiving is
  automatic inside this single skill call. Failures surface as
  BRIDGE-PERSIST-WRITE-FAILED: <reason> status strings — read the
  reason, fix the shape, retry; never record a fact without its fresh
  receipt.
---

# das-write — durable, verified DAS writes (exec CLI form)

## Invocation (exec tool)

Map the `(metta "(add-atom ...)")` call to running the bridge script:

```
python3 skills/das-write/das_write_bridge.py '(metta "(add-atom &persistent (<expression>) \"<source-url>\" (stv 0.9 0.8))")'
```

The wrapped `(metta "...")` invocation form is accepted and unwrapped
mechanically; the bare form works identically:

```
python3 skills/das-write/das_write_bridge.py '(add-atom &persistent (<expression>) "<source-url>" (stv 0.9 0.8))'
```

## The add-atom shape (v3, transparent provenance)

- `(add-atom &persistent <expr> "<ref>" [(stv s c)])` — exactly one
  balanced expression, one quoted source reference, optionally one
  `(stv strength confidence)` truth value (each in 0.0..1.0).
- `<ref>` must be an http(s) URL (≤480 chars, no whitespace) or an
  absolute path inside the configured source roots. `git:` citations
  are rejected — archiving is automatic.
- Omitting `<ref>` is rejected (a source reference is required on
  persistent writes).
- `(remove-atom &persistent ...)` is not bridged yet — nothing is
  removed from DAS.
- The expression is capped at 2048 characters.

## Receipts and failure statuses

- Success (the ONLY write-success signal):
  `BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]`
  — `top=` is the stored atom's handle; copy it verbatim whenever you
  must refer to the stored atom.
- `BRIDGE-PERSIST-WRITE-FAILED: <reason>` — the write did not land.
  Read the reason, fix the form, retry.
- `()` — the call was not an add-atom interception target (stock
  evaluation is the caller's decision).

## Environment (set by the deployment)

- `OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN` — write-bridge origin (exact http
  origin with an explicit port).
- `OPENCLAW_SUT_READ_PROXY_ORIGIN` — read-proxy origin (parity with the
  das-retrieve skill contract).
- `OPENCLAW_SUT_WORKSPACE` — workspace root; the receipt line is also
  appended, ISO-8601-prefixed, to `benchmark/persist-receipts.log` under
  the workspace (best-effort — it never changes the printed receipt).
- `OPENCLAW_SUT_DAS_ENABLED=1` — the opt-in gate; without it the script
  prints `()` and writes nothing.
