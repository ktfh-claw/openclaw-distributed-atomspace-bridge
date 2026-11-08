# STV Derivation Prompt — Windowless Room Look-Up

## The Prompt

"Derive the answer to the windowless-room look-up question from stored knowledge as a MeTTa derivation: formalize the question as a query clause, retrieve the supporting facts, and produce the grounded conclusion with (stv ...) truth values in the (|~ ...) derivation format, verifying each step against DAS receipts."

## Purpose

Tests whether the agent can produce a grounded MeTTa derivation of the windowless-room look-up answer — formalizing the question as a query clause, retrieving the supporting facts from DAS, and deriving the conclusion with (stv ...) truth values in the (|~ ...) derivation format, each step verified against DAS receipts.

## Expected Answer

**A grounded (|~ ...) derivation whose conclusion is the ceiling answer with (stv ...) truth values, each premise verified by a DAS retrieve receipt.**

## Reasoning Trace (Expected)

1. Formalize the question as a MeTTa query clause: the observer inside a windowless room looking up.
2. Retrieve the supporting facts from DAS: the room has a ceiling; the ceiling is above the observer; the ceiling is opaque (blocks the view of the sky).
3. Derive the conclusion with (stv ...) truth values in the (|~ ...) derivation format: the observer sees the ceiling.
4. Verify each step against DAS receipts (the retrieval receipts quoted in the answers file).

## Grading Criteria

- **PASS**: Agent produces a grounded (|~ ...) derivation whose conclusion is the ceiling answer with (stv ...) truth values, each premise verified by a DAS retrieve receipt.
- **FAIL**: Agent concludes sky/stars, or produces a derivation lacking (stv ...) truth values, or fails to verify premises against DAS receipts.
