# Floor Lamp Prompt — Windowless Room Variant

## The Prompt

"You turn on a lamp that is placed on the floor of a windowless room, then look straight up. What is visible above you? Distinguish between the light source below and what is above, and cite the stored facts for each step."

## Purpose

Tests whether the agent can distinguish the light source's position (a floor lamp — an artificial light source that illuminates the room interior/surfaces) from what is above (the ceiling — the first opaque surface above the observer) when answering what is visible looking straight up. The floor-lamp variant changes the light-source position, not the look-up answer: the ceiling is still what is visible above.

## Expected Answer

**The ceiling** (the room remains enclosed above the observer; the floor lamp illuminates the room interior/surfaces, and the first opaque surface above is the ceiling).

## Reasoning Trace (Expected)

1. The lamp on the floor is an artificial light source that illuminates the room interior and makes the room's surfaces visible.
2. The observer looks straight up from inside the windowless room.
3. The ceiling is above the observer — the first opaque surface, blocking the view of the sky.
4. Therefore: what is visible above is the ceiling (illuminated by the floor lamp).

## Grading Criteria

- **PASS**: Agent answers "the ceiling" (illuminated by the floor lamp) with correct reasoning trace citing DAS facts for each step.
- **FAIL**: Agent answers "sky"/"stars" (pattern-matching "look up" → "sky" without simulating the indoor scene), or ignores the light-source-position distinction.
