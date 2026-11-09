#!/usr/bin/env python3
"""oc3 audit mode unit tests — end-to-end battery grading on fixtures
(R2 acceptance 4 + R3 acceptance 5 wiring, spec
specs/oc3-research-audit-mode/spec.md).

Drives full_battery over a 2-case external question-pack/1 fixture:
all live IO stubbed (no docker, no sudo, no network — the oc3 series on
OVH is live), grade_case REAL — a full battery-mode grading pass on
fixtures. The pack's two cases cover both judge paths end-to-end:
- 'room-parts' carries an expected_answer -> the EXISTING A-gate judge
- 'open-question' has none -> the FAITHFULNESS judge (presented
  evidence injected at the wiring seam)

Also asserts the frozen-path acceptance: grading.py, history_parse.py,
provenance_check.py, llm_judge.py, background/ and the frozen prompt
files stay byte-identical vs origin/main.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..", "..")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import run_benchmark as rb

# ---------------------------------------------------------------------------
# fixture pack (question-pack/1): one expected-answer case + one
# faithfulness (no expected_answer) case
# ---------------------------------------------------------------------------

PACK_NAME = "fixture research pack"
ROOM_PARTS_QUERY = '(Evaluation (Predicate "has-part") (Concept "room") $X)'
WALL_EXPR = '(Evaluation (Predicate "has-part") (Concept "room") (Concept "wall"))'
FLOOR_EXPR = '(Evaluation (Predicate "has-part") (Concept "room") (Concept "floor"))'
OPEN_QUERY = '(Inheritance $X (Concept "ceiling"))'
OPAQUE_EXPR = '(Inheritance (Concept "ceiling") (Concept "opaque-surface"))'

FIXTURE_PACK = {
    "schema": "question-pack/1",
    "name": PACK_NAME,
    "cases": [
        {
            "id": "room-parts",
            "question": "What parts does a room have, per the stored knowledge?",
            "expected_answer": "Walls and a floor (and a ceiling).",
        },
        {
            "id": "open-question",
            "question": "What does the stored knowledge say the ceiling is?",
        },
    ],
}

FACTS_INDEX_TEXT = (
    "# Extraction record — fixture\n"
    f"expr {WALL_EXPR} top={'a' * 32}\n"
    f"expr {FLOOR_EXPR} top={'b' * 32}\n"
    f"expr {OPAQUE_EXPR} top={'c' * 32}\n"
    f"exec {WALL_EXPR} => ({WALL_EXPR} (stv 0.9 0.8))\n"
)

ANSWERS_TEXT = (
    "# Benchmark answers — fixture (battery)\n"
    "\n"
    "### CASE room-parts\n"
    "\n"
    f"QUERY: {ROOM_PARTS_QUERY}\n"
    "DAS_RETRIEVE_OK untrusted=true count=2 truncated=false results=[...]\n"
    f"FACTS: {WALL_EXPR}; {FLOOR_EXPR}\n"
    f"HANDLES: {'a' * 32} {'b' * 32}\n"
    f"REASONING: {ROOM_PARTS_QUERY}; {WALL_EXPR}; {FLOOR_EXPR}\n"
    "FINAL ANSWER (room-parts): a room has walls and a floor\n"
    "\n"
    "### CASE open-question\n"
    "\n"
    f"QUERY: {OPEN_QUERY}\n"
    "DAS_RETRIEVE_OK untrusted=true count=2 truncated=false results=[...]\n"
    f"FACTS: {OPAQUE_EXPR}\n"
    f"HANDLES: {'c' * 32}\n"
    f"REASONING: {OPEN_QUERY}; {OPAQUE_EXPR}\n"
    "FINAL ANSWER (open-question): the ceiling is an opaque surface\n"
)

def _history_line(query):
    """One das-retrieve history line with the JSON-escaped argument form
    (the real history channel serializes the query with escaped inner
    quotes — history_parse._unescape reverses it)."""
    return 'das-retrieve "' + query.replace('"', '\\"') + '"'


HISTORY_TEXT = (
    "; history trimmed by the benchmark harness (fixture)\n"
    + _history_line(ROOM_PARTS_QUERY) + "\n"
    + _history_line(OPEN_QUERY) + "\n"
)

BKGD_URL = ("https://raw.githubusercontent.com/ktfh-claw/low-cost-omega-setup/"
            "main/tests/reasoning-windowless-room/background/"
            "spatial-knowledge.md")


def _recon_payload(exprs, query):
    """A clean reconstruction payload for the fixture exprs (fully
    resolved ledger sources, no H_* conditions, no blocking rows)."""
    rows = [
        {"expr": e, "top_handle": "t" * 32, "stored": True,
         "classification": "stored_fact",
         "sources": [{"commit": "f" * 40, "ref": BKGD_URL,
                      "sha256": "e" * 64,
                      "entry_date": "2026-11-08T00:00:00Z",
                      "resolved": True, "legacy": False, "conditions": []}],
         "conditions": []}
        for e in exprs
    ]
    rows.append({"expr": query, "top_handle": None, "stored": False,
                 "classification": "query_clause", "sources": [],
                 "conditions": []})
    return {
        "per_expression": rows,
        "per_predicate": {},
        "handles_check": {"claimed": [], "derived": [], "conditions": []},
        "missing": [],
        "conditions": [],
        "source_paths": [],
    }


def _args(run_id, battery, **kw):
    return type("Args", (), {
        "run_id": run_id, "case": "", "battery": battery,
        "timeout_minutes": 75, "memory_volume": "/tmp/t-battery-memvol",
        "dry_run": False, "skip_report": True, "force": False,
        "write_bridge": "http://172.20.0.5:8080",
        "read_proxy": "http://172.20.0.3:8080",
        "agent_profile": "omega", "stall_minutes": 25,
        "trim_history": True, "keep_snapshots": True,
        "allow_dirty_backup": False, "judge_api_key": "",
        **kw,
    })()


def _run_battery_pack_e2e(run_id, judge_expected_ok=True,
                          judge_faith_ok=True):
    """Drive full_battery over the fixture pack with REAL grade_case and
    every live IO edge stubbed; returns (rc, grade_json, records,
    case_files) where records captures which judge saw which
    (case, answer) and case_files carries the per-case grade JSONs."""
    records = {"expected": [], "faith": []}

    def expected_judge(case, final_answer):
        records["expected"].append((dict(case), final_answer))
        return judge_expected_ok, {"judge_verdict":
                                    "TRUE" if judge_expected_ok else "FALSE",
                                    "stub": "expected"}

    def faith_judge(case, final_answer):
        records["faith"].append((dict(case), final_answer))
        return judge_faith_ok, {"judge_verdict":
                                "TRUE" if judge_faith_ok else "FALSE",
                                "judge_mode": "faithfulness",
                                "stub": "faithfulness"}

    def fake_read(path):
        return {
            "answers.md": ANSWERS_TEXT,
            "history.metta": HISTORY_TEXT,
            "facts-index.md": FACTS_INDEX_TEXT,
        }.get(Path(str(path)).name, "")

    originals = {
        name: getattr(rb, name)
        for name in ("RESULTS_DIR", "preflight", "setup_reasoning_phase",
                     "agent_case", "_copy_window_artifacts", "teardown",
                     "_sudo_write", "_sudo_read", "_resolve_endpoints",
                     "_census_persist_receipts", "collect_attestation",
                     "_run_reconstruction", "_http_post",
                     "_get_judge", "_get_faithfulness_judge")
    }
    saved_cache = dict(rb._PACK_CACHE)
    rb._PACK_CACHE.clear()
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rb.RESULTS_DIR = root
            pack_path = root / "fixture-pack.json"
            pack_path.write_text(json.dumps(FIXTURE_PACK), encoding="utf-8")

            # battery-mode window anchors: the reasoning-phase restart
            # per case (setup_reasoning_phase is stubbed, so the setup
            # JSONs are pre-written as fixtures)
            for cid in ("room-parts", "open-question"):
                (root / run_id).mkdir(parents=True, exist_ok=True)
                (root / run_id
                 / f"setup-reasoning-case-{cid}.json").write_text(
                    json.dumps({"restarted_at": "2026-11-09T09:00:00Z"}),
                    encoding="utf-8")

            rb.preflight = lambda a: 0
            rb.setup_reasoning_phase = lambda a: 0
            rb.agent_case = lambda a: 0
            rb._copy_window_artifacts = lambda a, cid: None
            rb.teardown = lambda a: 0
            rb._sudo_write = lambda path, content, timeout=60.0: True
            rb._sudo_read = fake_read
            rb._resolve_endpoints = lambda a: None
            rb._census_persist_receipts = (
                lambda since, until, extra_logs="", profile=None,
                memory_volume=None: {"count": 1, "matched": ["fixture"],
                                     "window": [since, until]})
            rb.collect_attestation = (
                lambda args, case_id, since, until, query: {
                    "case_id": case_id, "agent_ip": "172.20.0.6",
                    "access_count": 1, "qe_pattern_match": True,
                    "window": [since, until]})
            rb._run_reconstruction = (
                lambda args, case_id, block, artifacts_dir:
                _recon_payload([WALL_EXPR, FLOOR_EXPR]
                               if case_id == "room-parts" else [OPAQUE_EXPR],
                               ROOM_PARTS_QUERY
                               if case_id == "room-parts" else OPEN_QUERY))
            rb._http_post = (
                lambda url, body, timeout=30.0: {"count": 2})
            rb._get_judge = lambda a: expected_judge
            rb._get_faithfulness_judge = lambda a: faith_judge

            rc = rb.full_battery(_args(run_id, str(pack_path)))
            grade_json = json.loads(
                (root / run_id / "grade.json").read_text(encoding="utf-8"))
            case_files = {}
            for cid in ("room-parts", "open-question"):
                case_files[cid] = json.loads(
                    (root / run_id / f"grade-case-{cid}.json").read_text(
                        encoding="utf-8"))
            return rc, grade_json, records, case_files
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)
        rb._PACK_CACHE.clear()
        rb._PACK_CACHE.update(saved_cache)


# ---------------------------------------------------------------------------
# the full battery-mode grading pass on fixtures (R2 acceptance 4)
# ---------------------------------------------------------------------------

def test_fixture_pack_full_battery_grading_pass():
    """A full battery-mode grading pass over the fixture pack: REAL
    grade_case per case (only live IO stubbed), both judge paths
    exercised, gate verdict PASS, grade.json records the pack."""
    rc, grade, records, _files = _run_battery_pack_e2e("t-battery-pack-e2e")
    assert rc == rb.GATE_PASS
    assert grade["mode"] == "battery"
    assert grade["gate_verdict"] == "PASS"
    assert grade["cases_passed"] == 2
    assert grade["cases_total"] == 2
    assert grade["battery_pack"]["name"] == PACK_NAME
    assert grade["battery_pack"]["path"].endswith("fixture-pack.json")
    for cid in ("room-parts", "open-question"):
        assert grade["per_case"][cid]["verdict"] == "PASS", cid
        # informationals only (the pack case's allowed source set is
        # empty, so P_SOURCE_SET_MISMATCH is expected — informational)
        blocking = [c for c in grade["per_case"][cid]["conditions"]
                    if c != "P_SOURCE_SET_MISMATCH"]
        assert blocking == [], (cid, grade["per_case"][cid]["conditions"])


def test_fixture_pack_expected_answer_case_uses_existing_judge():
    """The pack case WITH expected_answer is judged by the EXISTING
    A-gate judge (end-to-end through grade_case's seam)."""
    _rc, _grade, records, _files = _run_battery_pack_e2e("t-battery-pack-e2e-exp")
    assert len(records["expected"]) == 1
    case, answer = records["expected"][0]
    assert case["id"] == "room-parts"
    assert case["question"] == FIXTURE_PACK["cases"][0]["question"]
    assert case["expected_answer"] == FIXTURE_PACK["cases"][0]["expected_answer"]
    assert answer == "a room has walls and a floor"
    # the existing judge sees NO presented-evidence injection
    assert "presented_evidence" not in case
    # and the faithfulness judge was never consulted for this case
    assert all(c["id"] != "room-parts" for c, _ in records["faith"])


def test_fixture_pack_no_expected_answer_case_uses_faithfulness_judge():
    """The pack case WITHOUT expected_answer is judged by the
    FAITHFULNESS judge, with the presented evidence (FACTS/REASONING
    lines, verbatim) injected at the wiring seam."""
    _rc, _grade, records, _files = _run_battery_pack_e2e("t-battery-pack-e2e-faith")
    assert len(records["faith"]) == 1
    case, answer = records["faith"][0]
    assert case["id"] == "open-question"
    assert case["question"] == FIXTURE_PACK["cases"][1]["question"]
    assert answer == "the ceiling is an opaque surface"
    # no ground truth invented for a research question
    assert "expected_answer" not in case
    # the presented evidence = the block's FACTS + REASONING lines
    assert case["presented_evidence"] == (
        f"FACTS: {OPAQUE_EXPR}\n"
        f"REASONING: {OPEN_QUERY}; {OPAQUE_EXPR}")
    # and the existing judge was never consulted for this case
    assert all(c["id"] != "open-question" for c, _ in records["expected"])


def test_fixture_pack_grade_case_jsons_record_judge_mode():
    """The per-case grade JSONs record which judge ran (the existing
    judge's detail vs judge_mode=faithfulness) and the gate evidence."""
    run_id = "t-battery-pack-e2e-jsons"
    rc, _grade, _records, case_files = _run_battery_pack_e2e(run_id)
    assert rc == rb.GATE_PASS
    expected_detail = case_files["room-parts"]["detail"]["judge"]
    assert expected_detail["stub"] == "expected"
    assert "judge_mode" not in expected_detail
    faith_detail = case_files["open-question"]["detail"]["judge"]
    assert faith_detail["judge_mode"] == "faithfulness"
    for cid in ("room-parts", "open-question"):
        g = case_files[cid]
        assert g["verdict"] == "PASS", (cid, g["conditions"])
        assert g["conditions"] == ["P_SOURCE_SET_MISMATCH"], \
            (cid, g["conditions"])
        assert g["mechanism_verdict"] == "PASS"


def test_fixture_pack_faithfulness_false_fails_the_gate():
    """The faithfulness verdict maps to the gate signal: FALSE ->
    A_WRONG -> gate FAIL (exit 2) — an answer that overreaches its
    presented evidence never passes."""
    rc, grade, records, _files = _run_battery_pack_e2e(
        "t-battery-pack-e2e-false", judge_faith_ok=False)
    assert rc == rb.GATE_FAIL
    assert grade["gate_verdict"] == "FAIL"
    assert grade["cases_passed"] == 1
    open_case = grade["per_case"]["open-question"]
    assert open_case["verdict"] == "FAIL"
    assert "A_WRONG" in open_case["conditions"]
    # the expected-answer case is unaffected (independent grading)
    assert grade["per_case"]["room-parts"]["verdict"] == "PASS"
    assert len(records["faith"]) == 1


def test_fixture_pack_expected_false_fails_the_gate():
    """The EXISTING judge's FALSE verdict still fails its case (the
    expected-answer semantics are exactly unchanged)."""
    rc, grade, _records, _files = _run_battery_pack_e2e(
        "t-battery-pack-e2e-expfalse", judge_expected_ok=False)
    assert rc == rb.GATE_FAIL
    assert grade["per_case"]["room-parts"]["verdict"] == "FAIL"
    assert "A_WRONG" in grade["per_case"]["room-parts"]["conditions"]
    assert grade["per_case"]["open-question"]["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# frozen-path acceptance (plan verification: git diff vs main empty)
# ---------------------------------------------------------------------------

FROZEN_PATHS = [
    "tests/reasoning-windowless-room/grading.py",
    "tests/reasoning-windowless-room/history_parse.py",
    "tests/reasoning-windowless-room/provenance_check.py",
    "tests/reasoning-windowless-room/llm_judge.py",
    "tests/reasoning-windowless-room/background",
    "tests/reasoning-windowless-room/prompts/original-prompt.md",
    "tests/reasoning-windowless-room/prompts/false-statement-prompt.md",
    "tests/reasoning-windowless-room/prompts/unsolvable-unrelated-prompt.md",
    "tests/reasoning-windowless-room/prompts/expected-answer.md",
]


def test_frozen_paths_byte_identical_vs_origin_main():
    """Hard constraint: the frozen gate/judge/background/prompt files
    stay byte-identical (diff vs origin/main empty — only facts.py
    additions are allowed on the battery branch)."""
    result = subprocess.run(["git", "diff", "origin/main", "--"] + FROZEN_PATHS,
                            capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, f"git diff failed: {result.stderr}"
    assert result.stdout.strip() == "", \
        f"frozen paths have diffs vs origin/main:\n{result.stdout}"


def test_facts_py_additions_only_vs_origin_main():
    """facts.py may change only additively (the battery branch's
    BATTERY_CASES block); no deletions or in-place edits."""
    result = subprocess.run(
        ["git", "diff", "origin/main", "--",
         "tests/reasoning-windowless-room/facts.py"],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        if line.startswith(("---", "+++", "@@", "diff", "index", " ")):
            continue  # headers + unchanged context lines
        assert line.startswith("+"), \
            f"facts.py diff must be additions-only, got: {line!r}"
