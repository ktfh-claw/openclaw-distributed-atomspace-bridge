#!/usr/bin/env python3
"""oc3 audit mode unit tests — external question packs (R2, spec
specs/oc3-research-audit-mode/spec.md).

Covers the question-pack/1 loader/validator (question_pack.py) and the
--battery path-or-built-in wiring (run_benchmark):
- valid load (full pack, minimal pack, defaults for optional fields)
- every rejection branch (unreadable file, invalid JSON, shape errors,
  schema errors, bad ids, duplicate ids, empty question, bad optional
  field types, TEST_CASES/BATTERY_CASES id collisions, reserved ids)
- built-in id 'battery' compatibility (byte-identical behavior)
- _case_by_id pack resolution (pack ids resolve only with the pack
  path; standard/built-in resolution unchanged)

All tests are pure logic (temp files, monkeypatched harness seams —
no docker, no sudo, no network).
"""
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import facts
import question_pack as qp
import run_benchmark as rb

TEST_IDS = [c["id"] for c in facts.TEST_CASES]
BATTERY_IDS = [c["id"] for c in facts.BATTERY_CASES]

GOOD_PACK = {
    "schema": "question-pack/1",
    "name": "research probe pack",
    "cases": [
        {
            "id": "room-parts",
            "question": "What parts does a room have?",
            "expected_answer": "Walls, a floor, and a ceiling.",
            "required_facts": [
                '(Evaluation (Predicate "has-part") (Concept "room") (Concept "wall"))'
            ],
            "source_expectations": ["spatial-knowledge.md"],
        },
        {
            # no expected_answer -> the faithfulness judge (R3)
            "id": "open-research-question",
            "question": "Which stored knowledge supports the look-up answer?",
        },
    ],
}


def _write_pack(tmp_path, data, name="pack.json"):
    p = Path(tmp_path) / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def _expect_reject(path, *fragments):
    try:
        qp.load_pack(path, test_case_ids=TEST_IDS,
                     battery_case_ids=BATTERY_IDS)
    except qp.QuestionPackError as e:
        for frag in fragments:
            assert frag in str(e), f"{frag!r} not in {str(e)!r}"
        return
    raise AssertionError(f"expected QuestionPackError for {path!r}")


# ---------------------------------------------------------------------------
# valid loads
# ---------------------------------------------------------------------------

def test_valid_pack_loads_and_normalizes(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, GOOD_PACK)
        pack = qp.load_pack(path, test_case_ids=TEST_IDS,
                            battery_case_ids=BATTERY_IDS)
        assert pack["schema"] == "question-pack/1"
        assert pack["name"] == "research probe pack"
        assert pack["source_path"] == path
        assert [c["id"] for c in pack["cases"]] == [
            "room-parts", "open-research-question"]
        first, second = pack["cases"]
        assert first["question"] == "What parts does a room have?"
        assert first["expected_answer"] == "Walls, a floor, and a ceiling."
        assert first["required_facts"] == [
            '(Evaluation (Predicate "has-part") (Concept "room") (Concept "wall"))']
        assert first["source_expectations"] == ["spatial-knowledge.md"]
        # no expected_answer -> the key must be ABSENT (never an empty
        # string): its absence selects the faithfulness judge
        assert "expected_answer" not in second
        assert second["required_facts"] == []
        assert second["source_expectations"] == []


def test_valid_minimal_pack_name_optional(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {
            "schema": "question-pack/1",
            "cases": [{"id": "only-case", "question": "Why?"}],
        })
        pack = qp.load_pack(path)
        assert pack["name"] is None
        assert len(pack["cases"]) == 1
        c = pack["cases"][0]
        assert c["id"] == "only-case"
        assert c["question"] == "Why?"
        assert "expected_answer" not in c
        assert "prompt" not in c


def test_valid_pack_prompt_override_optional(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {
            "schema": "question-pack/1",
            "cases": [{
                "id": "prompted-case",
                "question": "short question",
                "prompt": "A much longer, fully-worded research prompt.",
            }],
        })
        pack = qp.load_pack(path)
        assert pack["cases"][0]["prompt"] == \
            "A much longer, fully-worded research prompt."
        assert pack["cases"][0]["question"] == "short question"


# ---------------------------------------------------------------------------
# rejection branches
# ---------------------------------------------------------------------------

def test_reject_unreadable_file():
    _expect_reject("/nonexistent/pack-does-not-exist.json",
                   "cannot read question pack")


def test_reject_invalid_json(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "pack.json"
        p.write_text("{not json", encoding="utf-8")
        _expect_reject(str(p), "not valid JSON")


def test_reject_non_object_top_level(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, ["not", "an", "object"])
        _expect_reject(path, "JSON object")


def test_reject_missing_schema(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"cases": [{"id": "a-case",
                                           "question": "Q?"}]})
        _expect_reject(path, "schema")


def test_reject_wrong_schema(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/2",
                                "cases": [{"id": "a-case",
                                           "question": "Q?"}]})
        _expect_reject(path, "unsupported question-pack schema")


def test_reject_missing_cases(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1"})
        _expect_reject(path, "'cases' list")


def test_reject_empty_cases(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "cases": []})
        _expect_reject(path, "empty 'cases' list")


def test_reject_case_not_object(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1",
                                "cases": ["not an object"]})
        _expect_reject(path, "JSON object")


def test_reject_missing_id(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1",
                                "cases": [{"question": "Q?"}]})
        _expect_reject(path, "non-empty string 'id'")


def test_reject_empty_id(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for bad in ("", "   "):
            path = _write_pack(td, {"schema": "question-pack/1",
                                    "cases": [{"id": bad,
                                               "question": "Q?"}]})
            _expect_reject(path, "non-empty string 'id'")


def test_reject_bad_id_charset(tmp_path=None):
    """The gate's answers-block header regex accepts exactly [a-z0-9-]+;
    pack ids get the strict kebab-case form of it."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for bad in ("UPPER", "with space", "under_score", "trailing-",
                    "-leading", "double--hyphen"):
            path = _write_pack(td, {"schema": "question-pack/1",
                                    "cases": [{"id": bad,
                                               "question": "Q?"}]})
            _expect_reject(path, "kebab-case")


def test_reject_duplicate_ids(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "cases": [
            {"id": "same-id", "question": "Q1?"},
            {"id": "same-id", "question": "Q2?"},
        ]})
        _expect_reject(path, "duplicate case id", "same-id")


def test_reject_missing_question(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1",
                                "cases": [{"id": "a-case"}]})
        _expect_reject(path, "non-empty string 'question'")


def test_reject_empty_question(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1",
                                "cases": [{"id": "a-case",
                                           "question": "   "}]})
        _expect_reject(path, "non-empty string 'question'")


def test_reject_empty_expected_answer_selects_faithfulness_instead(tmp_path=None):
    """An explicitly-empty expected_answer is degenerate: provide a real
    one or OMIT the field (omission selects the faithfulness judge)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "cases": [
            {"id": "a-case", "question": "Q?", "expected_answer": "  "}]})
        _expect_reject(path, "expected_answer")


def test_reject_bad_required_facts_type(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "cases": [
            {"id": "a-case", "question": "Q?",
             "required_facts": "not-a-list"}]})
        _expect_reject(path, "required_facts", "list")


def test_reject_empty_required_facts_member(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "cases": [
            {"id": "a-case", "question": "Q?",
             "required_facts": ["(ok)", "  "]}]})
        _expect_reject(path, "required_facts", "non-empty strings")


def test_reject_bad_source_expectations(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "cases": [
            {"id": "a-case", "question": "Q?",
             "source_expectations": [17]}]})
        _expect_reject(path, "source_expectations", "non-empty strings")


def test_reject_bad_name_type(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "name": 42,
                                "cases": [{"id": "a-case",
                                           "question": "Q?"}]})
        _expect_reject(path, "'name'")


def test_reject_collision_with_frozen_test_cases_ids(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for frozen in TEST_IDS:
            path = _write_pack(td, {"schema": "question-pack/1", "cases": [
                {"id": frozen, "question": "Q?"}]})
            _expect_reject(path, "frozen TEST_CASES id", frozen)


def test_reject_collision_with_builtin_battery_ids(tmp_path=None):
    """The built-in BATTERY_CASES ids are refused too: _case_by_id
    resolves them BEFORE pack cases, so a colliding pack id would be
    silently shadowed."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for bid in BATTERY_IDS:
            path = _write_pack(td, {"schema": "question-pack/1", "cases": [
                {"id": bid, "question": "Q?"}]})
            _expect_reject(path, "BATTERY_CASES id", bid)


def test_reject_reserved_extract_id(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write_pack(td, {"schema": "question-pack/1", "cases": [
            {"id": "extract", "question": "Q?"}]})
        _expect_reject(path, "reserved")


# ---------------------------------------------------------------------------
# --battery wiring: built-in id 'battery' vs pack path
# ---------------------------------------------------------------------------

def _clear_pack_cache():
    saved = dict(rb._PACK_CACHE)
    rb._PACK_CACHE.clear()
    return saved


def _restore_pack_cache(saved):
    rb._PACK_CACHE.clear()
    rb._PACK_CACHE.update(saved)


def test_builtin_battery_id_resolves_no_pack():
    assert rb._pack_cases("") == []
    assert rb._pack_cases("battery") == []


def test_case_by_id_resolves_pack_cases_with_path(tmp_path=None):
    import tempfile
    saved = _clear_pack_cache()
    try:
        with tempfile.TemporaryDirectory() as td:
            path = _write_pack(td, GOOD_PACK)
            for case in rb._pack_cases(path):
                resolved = rb._case_by_id(case["id"], path)
                assert resolved is not None, case["id"]
                assert resolved["id"] == case["id"]
                assert resolved["question"] == case["question"]
            # without the pack path the pack ids are unknown (standalone
            # per-case subcommands carry no --battery)
            assert rb._case_by_id("room-parts", "") is None
    finally:
        _restore_pack_cache(saved)


def test_case_by_id_standard_and_builtin_resolution_unchanged():
    for case in facts.TEST_CASES:
        assert rb._case_by_id(case["id"]) is case
        assert rb._case_by_id(case["id"], "battery") is case
    for case in facts.BATTERY_CASES:
        assert rb._case_by_id(case["id"]) is case
        assert rb._case_by_id(case["id"], "battery") is case
    assert rb._case_by_id("no-such-case") is None


def test_pack_does_not_shadow_standard_or_builtin_ids(tmp_path=None):
    """A pack id can never shadow TEST_CASES/BATTERY_CASES ids — the
    collision guard refuses those ids at load time."""
    import tempfile
    saved = _clear_pack_cache()
    try:
        with tempfile.TemporaryDirectory() as td:
            path = _write_pack(td, GOOD_PACK)
            # 'room-parts' vs the standard/built-in ids are distinct;
            # standard resolution still wins for ITS ids
            assert rb._case_by_id("original", path)["id"] == "original"
            assert rb._case_by_id("stars-claim", path)["id"] == "stars-claim"
            assert rb._case_by_id("room-parts", path)["id"] == "room-parts"
    finally:
        _restore_pack_cache(saved)


def test_pack_load_is_memoized_per_path(tmp_path=None):
    import tempfile
    saved = _clear_pack_cache()
    try:
        with tempfile.TemporaryDirectory() as td:
            path = _write_pack(td, GOOD_PACK)
            first = rb._load_battery_pack(path)
            second = rb._load_battery_pack(path)
            assert first is second, "the pack loads once per path (memoized)"
    finally:
        _restore_pack_cache(saved)


def test_battery_flag_accepts_path_value():
    parser = rb.build_parser()
    args = parser.parse_args(["full", "--battery", "/some/pack.json"])
    assert args.battery == "/some/pack.json"
    args = parser.parse_args(["full", "--battery", "battery"])
    assert args.battery == "battery"
    args = parser.parse_args(["full"])
    assert args.battery == ""


def test_full_battery_invalid_pack_is_clear_harness_error(tmp_path=None):
    """An invalid pack path aborts full_battery with GATE_ERROR BEFORE
    preflight (a clear message, no live phase runs)."""
    import tempfile
    calls = []
    with tempfile.TemporaryDirectory() as td:
        saved = _clear_pack_cache()
        saved_preflight = rb.preflight
        rb.preflight = lambda a: (calls.append("preflight"), 0)[1]
        try:
            bad = _write_pack(td, {"schema": "question-pack/1", "cases": [
                {"id": "original", "question": "Q?"}]})
            args = type("Args", (), {
                "run_id": "t-battery-badpack", "case": "",
                "battery": bad, "timeout_minutes": 75,
                "memory_volume": "/tmp/t-battery-memvol",
                "dry_run": False, "skip_report": True,
                "write_bridge": "http://172.20.0.5:8080",
                "read_proxy": "http://172.20.0.3:8080",
                "agent_profile": "omega",
            })()
            assert rb.full_battery(args) == rb.GATE_ERROR
            assert calls == [], "no live phase may run on an invalid pack"
        finally:
            rb.preflight = saved_preflight
            _restore_pack_cache(saved)
