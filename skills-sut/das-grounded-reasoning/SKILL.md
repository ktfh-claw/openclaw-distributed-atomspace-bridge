---
name: das-grounded-reasoning
description: >-
  WHY: grounded reasoning answers questions strictly from the DAS
  knowledge base; an answer is justified ONLY by das-retrieve evidence,
  never by parametric memory. WHEN: call it whenever a question must be
  answered from stored knowledge — formalize the question into MeTTa,
  retrieve from DAS, execute the reasoning, answer strictly from the
  stored facts. HOW: (1) read the checkpoint manifest (the phase
  boundary between extraction and reasoning — it records which
  predicates exist, verbatim, for query reuse) via exec: python3
  skills/das-grounded-reasoning/das_grounded_reasoning.py
  '{"action": "read_checkpoint"}'; (2) formalize the question as one
  MeTTa clause — ground one side with a quoted literal, bind the target
  with a $variable, keep the stored arity/shape and direction; (3)
  retrieve from DAS via the das-retrieve skill — quote the real tool
  output; count=0 means absent OR wrongly-shaped (before concluding
  absence, re-probe once with the complementary direction and once with
  the exact spelling from your extraction record); (4) execute the
  reasoning with the metta skill — NAL/PLN operators are STRICTLY
  2-ARGUMENT; (5) answer strictly from the DAS KB — never invent
  content, never fabricate handles. One question at a time: complete
  the full retrieve-reason-answer cycle for the current question before
  starting the next.
---

# das-grounded-reasoning — answer strictly from the DAS knowledge base

## Procedure (the description above is the contract; this wires the exec forms)

1. **Read the checkpoint manifest** (the phase boundary between
   extraction and reasoning — it records which predicates exist,
   verbatim, for query reuse) via exec:

   ```
   python3 skills/das-grounded-reasoning/das_grounded_reasoning.py '{"action": "read_checkpoint"}'
   ```

   (or `{"action": "read_checkpoint", "corpus": "<id>"}` for a specific
   corpus). The manifest content returns verbatim — reuse its exact
   expressions; never paraphrase, rename, or re-translate them.

2. **Formalize the question as one MeTTa clause** — ground one side
   with a quoted literal, bind the target with a `$variable`, keep the
   stored arity/shape and direction.
3. **Retrieve from DAS via the das-retrieve skill** (exec
   `skills/das-retrieve/das_retrieve.py '<query-json>'`) — quote the
   real tool output. `count=0` means absent OR wrongly-shaped: before
   concluding absence, re-probe once with the complementary direction
   (ground the other argument instead) and once with the exact spelling
   from your extraction record; if the exact-spelling probes are still
   0, the absence is real — report it honestly, never invent content
   to fill it.
4. **Execute the reasoning with the metta skill** (exec
   `skills/metta/metta_run.py '<s-expression>'`) — NAL/PLN operators
   are STRICTLY 2-ARGUMENT; quote the interpreter output verbatim
   including its `(stv ...)`.
5. **Answer strictly from the DAS KB** — recorded expressions verbatim;
   never invent content, never fabricate handles.

One question at a time: complete the full retrieve-reason-answer cycle
for the current question before starting the next.

## Receipts

- The manifest content (predicates verbatim) on `read_checkpoint`
  success.
- `DAS-GROUNDED-REASONING-FAILED: <reason>` — read the reason, fix the
  payload or write the checkpoint first, retry.

## Environment (set by the deployment)

- `OPENCLAW_SUT_WORKSPACE` — workspace root (the manifest directory is
  `knowledge-checkpoints/` under it).
- `OPENCLAW_SUT_DAS_ENABLED=1` — the opt-in gate.
