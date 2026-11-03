---
name: das-extract-knowledge
description: >-
  WHY: knowledge extraction builds a DAS knowledge base from a text
  corpus (files, websites, text bases) by deriving MeTTa predicate
  expressions (facts) and persisting them via the das-write skill
  (add-atom persistence path); a fact is justified ONLY by a
  BRIDGE-PERSIST-OK receipt, never by parametric memory or paraphrase.
  WHEN: call it whenever a task requires building a knowledge base from
  a text corpus — extract predicates from the corpus, persist them via
  the das-write skill (add-atom persistence path), and write a
  checkpoint manifest recording what was extracted. HOW: (1) read the
  corpus ONCE — each source file exactly once, no re-reading after
  processing; (2) derive predicate clauses (facts) from the text — keep
  the full stored arity and shape, ground arguments with quoted
  literals; (3) persist EACH ONE via the das-write skill: python3
  skills/das-write/das_write_bridge.py '(metta "(add-atom &persistent
  (<expression>) \"<source-url>\" (stv 0.9 0.8))")' — success is ONLY
  BRIDGE-PERSIST-OK: verified=<n> top=<handle>; (4) after EACH receipt,
  IMMEDIATELY append ONE line to the extraction record: expr
  <the-exact-expression> top=<handle> — the handle copied VERBATIM from
  the receipt's top= field; (5) write the checkpoint manifest
  (predicates + receipts/handles + sources + timestamp) via exec:
  python3 skills/das-extract-knowledge/das_extract_knowledge.py
  '{"action": "checkpoint", "corpus": "<corpus-id>", "predicates":
  [{"expression": "...", "handle": "...", "source": "..."}]}' — the
  manifest lands in knowledge-checkpoints/<corpus-id>.md
  (workspace-relative) and is the reasoning phase's entry point. Bounded
  single-pass: extract each fact once, record it, do not loop — never
  re-read a source file after processing it, never re-extract a fact
  already recorded.
---

# das-extract-knowledge — generic single-pass knowledge extraction

## Procedure (the description above is the contract; this wires the exec forms)

1. **Read the corpus ONCE** — each source file exactly once, no
   re-reading after processing (use the source list the task gives you;
   treat its paths as authoritative).
2. **Derive predicate clauses (facts)** from the text — keep the full
   stored arity and shape, ground arguments with quoted literals.
3. **Persist EACH ONE via the das-write skill** (exec):

   ```
   python3 skills/das-write/das_write_bridge.py '(metta "(add-atom &persistent (<expression>) \"<source-url>\" (stv 0.9 0.8))")'
   ```

   Success is ONLY `BRIDGE-PERSIST-OK: verified=<n> top=<handle>`.
4. **After EACH receipt, IMMEDIATELY append ONE line** to the
   extraction record (the path the task gives you; treat it as the
   authoritative argument): `expr <the-exact-expression>
   top=<handle>` — the handle copied VERBATIM from the receipt's `top=`
   field. ONE line per receipt — never batch.
5. **Write the checkpoint manifest** (predicates + receipts/handles +
   sources + timestamp) via exec:

   ```
   python3 skills/das-extract-knowledge/das_extract_knowledge.py '{"action": "checkpoint", "corpus": "<corpus-id>", "predicates": [{"expression": "<expr>", "handle": "<handle>", "source": "<ref>"}]}'
   ```

   The manifest lands in `knowledge-checkpoints/<corpus-id>.md`
   (workspace-relative) and is the reasoning phase's entry point into
   the knowledge base. Success: `CHECKPOINT-WRITTEN: <path>`.

## Bounded single-pass discipline

Extract each fact once, record it, do not loop — never re-read a
source file after processing it, never re-extract a fact already
recorded. If a result is already recorded, do NOT redo it — reuse the
recorded url/handle/expression.

## Receipts

- `CHECKPOINT-WRITTEN: <path>` — the manifest append succeeded.
- `DAS-EXTRACT-KNOWLEDGE-FAILED: <reason>` — read the reason, fix the
  payload, retry.

## Environment (set by the deployment)

- `OPENCLAW_SUT_WORKSPACE` — workspace root (the manifest directory is
  `knowledge-checkpoints/` under it).
- `OPENCLAW_SUT_DAS_ENABLED=1` — the opt-in gate.
