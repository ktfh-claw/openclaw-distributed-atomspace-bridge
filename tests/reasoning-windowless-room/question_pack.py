"""External question packs for the oc3 research Q&A audit mode (spec:
specs/oc3-research-audit-mode/spec.md R2).

``full --battery <pack>`` accepts the built-in id ``battery`` (the 5
BATTERY_CASES, byte-compatible) OR a filesystem path to a
question-pack/1 JSON file:

    {
      "schema": "question-pack/1",
      "name": "optional human name",
      "cases": [
        {
          "id": "kebab-case-unique",
          "question": "the question text",
          "prompt": "optional full prompt text override",
          "required_facts": ["optional normalized MeTTa expressions"],
          "expected_answer": "optional expected answer for substance judging",
          "source_expectations": ["optional source refs the agent must cite"]
        }
      ]
    }

Validation (load_pack): schema field present + exact, non-empty case list,
unique kebab-case ids (the gate's answers-block header regex
``### CASE <id>`` accepts exactly ``[a-z0-9-]+``), non-empty question, and
a collision guard against the frozen TEST_CASES ids — plus the built-in
BATTERY_CASES ids and the reserved extraction pseudo-case id ``extract``
(_case_by_id would otherwise silently shadow the pack case, and a pack
``unsolvable``/``original`` id would hijack the gate's id-keyed
exemptions). required_facts / expected_answer / source_expectations are
all optional; an ABSENT expected_answer selects the faithfulness judge
(R3). External packs run exactly like the built-in battery: no
cleanup-das, no extraction — live-KB reuse.

The normalized case dicts carry the keys the per-case flow reads
(``id`` for gate_case, ``question``/``expected_answer`` for the judges,
``prompt`` as the rendered-question override) — deliberately the same
dict shape as TEST_CASES/BATTERY_CASES entries.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PACK_SCHEMA = "question-pack/1"

# The gate's answers-block header regex (grading.CASE_BLOCK_RE) accepts
# exactly [a-z0-9-]+; packs get the strict kebab-case form of it.
CASE_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Reserved harness ids a pack case may never take: the run-level
# extraction pseudo-case id (snapshot/record naming namespace).
RESERVED_IDS = ("extract",)


class QuestionPackError(ValueError):
    """Invalid question pack — str(e) is the clear, single-line cause."""


def _reject(msg: str) -> None:
    raise QuestionPackError(msg)


def _require_str_list(case_id: str, field: str, value) -> list[str]:
    """Validate an optional list-of-non-empty-strings case field."""
    if value is None:
        return []
    if not isinstance(value, list):
        _reject(f"case {case_id!r}: {field!r} must be a list of strings")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _reject(f"case {case_id!r}: {field!r} entries must be "
                    f"non-empty strings")
        out.append(item.strip())
    return out


def _validate_case(case: dict, seen_ids: set[str],
                   test_case_ids, battery_case_ids) -> dict:
    """Validate one pack case dict; return the normalized case dict."""
    if not isinstance(case, dict):
        _reject("each pack case must be a JSON object")
    cid = case.get("id")
    if not isinstance(cid, str) or not cid.strip():
        _reject("each pack case needs a non-empty string 'id'")
    cid = cid.strip()
    if not CASE_ID_RE.match(cid):
        _reject(f"case id {cid!r} must be kebab-case "
                f"(lowercase letters/digits/hyphens, e.g. 'my-case-1')")
    if cid in seen_ids:
        _reject(f"duplicate case id in pack: {cid!r}")
    seen_ids.add(cid)
    if cid in RESERVED_IDS:
        _reject(f"case id {cid!r} is reserved by the harness")
    frozen = set(test_case_ids or ())
    if cid in frozen:
        _reject(f"case id {cid!r} collides with a frozen TEST_CASES id")
    built_in = set(battery_case_ids or ())
    if cid in built_in:
        _reject(f"case id {cid!r} collides with a built-in BATTERY_CASES id")

    question = case.get("question")
    if not isinstance(question, str) or not question.strip():
        _reject(f"case {cid!r} needs a non-empty string 'question'")
    question = question.strip()

    prompt = case.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, str) or not prompt.strip():
            _reject(f"case {cid!r}: 'prompt' must be a non-empty string "
                    f"when present")
        prompt = prompt.strip()

    expected = case.get("expected_answer")
    if expected is not None:
        if not isinstance(expected, str) or not expected.strip():
            _reject(f"case {cid!r}: 'expected_answer' must be a non-empty "
                    f"string when present — omit it to select the "
                    f"faithfulness judge")
        expected = expected.strip()

    normalized = {
        "id": cid,
        "question": question,
        "required_facts": _require_str_list(cid, "required_facts",
                                            case.get("required_facts")),
        "source_expectations": _require_str_list(
            cid, "source_expectations", case.get("source_expectations")),
    }
    if prompt is not None:
        normalized["prompt"] = prompt
    if expected is not None:
        # absent expected_answer selects the faithfulness judge (R3) —
        # the key must stay ABSENT, never an empty string
        normalized["expected_answer"] = expected
    return normalized


def load_pack(path: str, test_case_ids=(), battery_case_ids=()) -> dict:
    """Load + validate a question-pack/1 JSON file; return the normalized
    pack dict {"schema", "name", "source_path", "cases"}.

    Raises QuestionPackError (a ValueError) with a clear one-line cause
    on any invalid pack: unreadable file, invalid JSON, missing/wrong
    schema, missing/empty cases list, bad case shape, duplicate ids, or
    a collision with the frozen TEST_CASES ids / built-in BATTERY_CASES
    ids / reserved harness ids.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        _reject(f"cannot read question pack: {e}")
    try:
        data = json.loads(raw)
    except ValueError as e:
        _reject(f"question pack is not valid JSON: {e}")
    if not isinstance(data, dict):
        _reject("question pack must be a JSON object")
    schema = data.get("schema")
    if schema is None:
        _reject("question pack missing the 'schema' field "
                f"(expected {PACK_SCHEMA!r})")
    if schema != PACK_SCHEMA:
        _reject(f"unsupported question-pack schema {schema!r} "
                f"(expected {PACK_SCHEMA!r})")
    cases = data.get("cases")
    if not isinstance(cases, list):
        _reject("question pack needs a 'cases' list")
    if not cases:
        _reject("question pack has an empty 'cases' list")

    name = data.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        _reject("question pack 'name' must be a non-empty string when present")

    seen: set[str] = set()
    normalized_cases = [
        _validate_case(case, seen, test_case_ids, battery_case_ids)
        for case in cases
    ]
    return {
        "schema": PACK_SCHEMA,
        "name": (name or "").strip() or None,
        "source_path": str(p),
        "cases": normalized_cases,
    }
