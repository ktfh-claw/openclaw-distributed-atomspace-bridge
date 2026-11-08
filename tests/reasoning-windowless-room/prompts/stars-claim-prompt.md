# Stars Claim Prompt — Windowless Room Variant

## The Prompt

"A friend claims that in a windowless room with the lights on, looking up you can see the stars at night. Refute or confirm this claim strictly from stored knowledge, showing each retrieval step and which background file each fact came from."

## Purpose

Tests whether the agent can refute a false claim about a windowless room — the long-chain refutation that requires combining the room-structure facts (ceiling above, blocks the view of the sky) with the windowless-room light facts (no natural light enters; only artificial light available) instead of pattern-matching "look up → sky/stars".

## Expected Answer

**Refuted** — in a windowless room the ceiling blocks the view of the sky/stars; no natural light enters.

## Reasoning Trace (Expected)

1. The windowless room is an enclosed space with no openings to the exterior — the ceiling is above the observer.
2. The ceiling blocks the view of the sky.
3. The windowless room admits no natural light — the stars are not visible from inside.
4. Therefore: the claim is REFUTED — the observer looking up sees the ceiling, not the stars.

## Grading Criteria

- **PASS**: Agent refutes the claim with correct reasoning trace citing DAS facts (ceiling blocks the sky; no natural light enters a windowless room).
- **FAIL**: Agent affirms the claim (stars visible), or fails to cite the stored facts for each step.
