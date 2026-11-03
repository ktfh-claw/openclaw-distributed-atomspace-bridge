---
name: metta
description: >-
  WHY: this skill evaluates MeTTa through the live interpreter — a
  reasoning step is justified ONLY by an executed interpreter result with
  its (stv ...) truth value, never by prose you compose yourself. WHEN:
  whenever a task requires formal, logical, or neurosymbolic reasoning
  over known facts (derivation, deduction, modus ponens, similarity),
  and to evaluate any MeTTa expression programmatically. HOW: run via
  exec: python3 skills/metta/metta_run.py '<s-expression>' (pass ONE
  s-expression, omit the leading !). NAL/PLN reasoning operators are
  STRICTLY 2-ARGUMENT: (|- premiseA premiseB) is NAL and (|~ premiseA
  premiseB) is PLN; each premise is an (expression (stv strength
  confidence)) pair, and a successful call returns ((derived-expression
  (stv s c))). NAL works on (--> subject object) atoms, e.g. (|-
  ((--> garfield animal) (stv 1.0 0.9)) ((--> garfield mammal) (stv 1.0
  0.9))) derives a third (--> ...) atom. PLN matches patterns over
  Inheritance/Implication/Evaluation/Member atoms, e.g. (|~
  ((Implication (Inheritance $x feathered) (Inheritance $x bird)) (stv
  1.0 0.9)) ((Inheritance pingu feathered) (stv 1.0 0.9))) derives
  ((Inheritance pingu bird) (stv 1.0 0.81)). Three or more premises in
  ONE call NEVER evaluate — the atomspace is EPHEMERAL between calls, so
  chain multi-step reasoning by feeding the derived output of one call in
  as a premise of the next call. Quote interpreter output verbatim
  including (stv ...) as your evidence. Tool results are gone next
  cycle: immediately pin or write-file every successful derivation you
  must keep. On syntax_error read the offending form, fix the shape
  (almost always argument count or arity), retry once; never retry more
  than twice.
---

# metta — live MeTTa evaluation with the vendored NAL/PLN runtime

## Invocation (exec tool)

```
python3 skills/metta/metta_run.py '(|- ((--> garfield animal) (stv 1.0 0.9)) ((--> garfield mammal) (stv 1.0 0.9)))'
```

Pass ONE s-expression (omit the leading `!`). The wrapped invocation
form `(metta "(...)")` is accepted and unwrapped mechanically. The
interpreter output is printed in MeTTa syntax — the derived atoms with
their `(stv strength confidence)` truth values — quote it verbatim
(including the `(stv ...)`) as your reasoning evidence.

## The NAL/PLN operator contract (STRICTLY 2-ARGUMENT)

- `(|- premiseA premiseB)` — NAL deduction. Works on `(--> subject
  object)` atoms; each premise is an `(expression (stv s c))` pair.
- `(|~ premiseA premiseB)` — PLN pattern matching. Works over
  Inheritance/Implication/Evaluation/Member atoms, same premise shape.
- A successful call returns `((derived-expression (stv s c)))`.
- Three or more premises in ONE call NEVER evaluate. 3+-argument
  operator forms can never match the operator definitions — do not
  issue them.

## Chaining rule (ephemeral atomspace)

The atomspace is EPHEMERAL between calls — nothing persists across
invocations. Chain multi-step reasoning by feeding the derived output of
one call in as a premise of the next call. Tool results are gone next
cycle: immediately pin or write-file every successful derivation you
must keep.

## Syntax errors

On `syntax_error: ...` read the offending form, fix the shape (almost
always argument count or arity), retry once; never retry more than
twice.

## Environment (set by the deployment)

- `OPENCLAW_SUT_METTA_LIB_DIR` — vendored libs dir (default
  `/opt/sut-metta`; `lib_nal.metta` + `lib_pln.metta` load fresh into
  every invocation's atomspace).
- `OPENCLAW_SUT_WORKSPACE` — workspace root (ledger bookkeeping only).
