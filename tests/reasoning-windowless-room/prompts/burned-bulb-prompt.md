# Burned Bulb Prompt — Windowless Room Variant

## The Prompt

"An astronaut is sitting in a windowless room with a light bulb mounted on the ceiling. The bulb burns out and goes dark. What can the astronaut see when looking straight up, and why? Reason step by step strictly from the stored knowledge base: formalize each question as a MeTTa query, retrieve from DAS, and quote the receipts. Then state which stored facts led to the answer and which background file each came from."

## Purpose

Tests state-change reasoning — the light source (a ceiling-mounted bulb) burns out and goes dark; the room becomes dark (no active light source). The agent must still derive that the ceiling is the opaque surface above the observer (blocking the sky) and answer what is visible looking up: the (now-dark) ceiling, not the sky and not nothing.

## Expected Answer

**The ceiling** (dark — the room is unlit with no active light source, but the ceiling is still the opaque surface above, blocking the sky; nothing above it is visible).

## Reasoning Trace (Expected)

1. The bulb mounted on the ceiling burns out and goes dark — the room is now dark with no active light source.
2. The ceiling is still above the observer — the room remains enclosed; the ceiling still blocks the view of the sky.
3. Looking straight up, the astronaut sees the ceiling (dark, unlit) — not the sky and not the stars.
4. Therefore: the astronaut sees the (dark) ceiling; nothing above it is visible because the ceiling is opaque.

## Grading Criteria

- **PASS**: Agent answers "the ceiling" (dark) with correct reasoning trace citing DAS facts (room enclosed, ceiling above, no active light source) and quoting receipts for each step.
- **FAIL**: Agent answers "sky"/"stars" (the bulb is out, so no light pollution argument), or "nothing at all" (ignoring that the ceiling is still the opaque surface above), or fails to formalize the question as a MeTTa query.
