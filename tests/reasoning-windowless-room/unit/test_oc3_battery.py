#!/usr/bin/env python3
"""oc3 reasoning-battery unit tests (spec
specs/oc3-reasoning-battery/spec.md R4).

Covers the --battery mode additions:
- battery case definition shape/ids (BATTERY_CASES in facts.py)
- --battery flag parsing (build_parser)
- default full path unchanged (no battery -> shared-extraction flow,
  exact existing constants)
- preflight battery-mode KB probe (read-proxy probe for a
  windowless-room fact; aborts when the KB is absent)
- no-cleanup-in-battery-mode (the live KB is preserved)
- grade.json gate_verdict computation with battery cases

All tests are pure logic (monkeypatched IO — no docker, no sudo, no
network).
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import facts
import run_benchmark as rb


def _args(**kw):
    """Fake args namespace for the battery flow (mirrors the argparse
    surface the battery phases read)."""
    return type("Args", (), {
        "run_id": "t-battery", "case": "stars-claim", "battery": "battery",
        "timeout_minutes": 75, "memory_volume": "/tmp/t-battery-memvol",
        "dry_run": False, "skip_report": False,
        "write_bridge": "http://172.20.0.5:8080",
        "read_proxy": "http://172.20.0.3:8080",
        **kw,
    })()


# ---------------------------------------------------------------------------
# battery case definitions (spec R1)
# ---------------------------------------------------------------------------

def test_battery_cases_count():
    assert len(facts.BATTERY_CASES) == 5


def test_battery_case_ids_match_spec():
    ids = [c["id"] for c in facts.BATTERY_CASES]
    assert ids == ["stars-claim", "floor-lamp", "burned-bulb",
                   "stv-derivation", "color-probe"]


def test_battery_case_shape():
    """Same dict shape as TEST_CASES entries: id, prompt_file,
    question, expected_answer, grading, required_facts."""
    for case in facts.BATTERY_CASES:
        for key in ("id", "prompt_file", "question", "expected_answer",
                    "grading", "required_facts"):
            assert key in case, f"{case['id']} missing {key}"
        # prompt_file references a prompts/ file
        assert case["prompt_file"].startswith("prompts/")


def test_battery_required_facts_match_spec():
    """The exact required_facts sets the spec R1 pins (existing
    CANONICAL_FACTS ids; color-probe is the empty negative probe)."""
    expected = {
        "stars-claim": {"F04", "F05", "F11", "F12", "F14", "F15", "F18"},
        "floor-lamp": {"F04", "F12", "F14", "F16", "F17"},
        "burned-bulb": {"F04", "F12", "F14", "F16", "F31"},
        "stv-derivation": {"F04", "F11", "F12", "F14"},
        "color-probe": set(),
    }
    for case in facts.BATTERY_CASES:
        assert set(case["required_facts"]) == expected[case["id"]], \
            case["id"]


def test_battery_required_facts_exist_in_canonical():
    all_ids = set(f["id"] for f in facts.CANONICAL_FACTS)
    for case in facts.BATTERY_CASES:
        for fid in case["required_facts"]:
            assert fid in all_ids, f"{fid} not in CANONICAL_FACTS"


def test_battery_prompt_files_exist():
    for case in facts.BATTERY_CASES:
        pf = rb.HERE / case["prompt_file"]
        assert pf.is_file(), f"missing prompt file: {pf}"
        text = pf.read_text(encoding="utf-8")
        assert len(text.strip()) > 100, f"prompt too short: {pf}"


def test_battery_ids_resolve_via_case_by_id():
    """Battery case ids resolve through _case_by_id (the per-case
    reasoning flow's resolution hook); standard ids still resolve from
    TEST_CASES first."""
    for case in facts.BATTERY_CASES:
        assert rb._case_by_id(case["id"]) is not None, case["id"]
    for case in facts.TEST_CASES:
        assert rb._case_by_id(case["id"]) is not None, case["id"]
    # a battery id does not shadow a standard id
    assert rb._case_by_id("original")["prompt_file"].startswith("prompts/")


# ---------------------------------------------------------------------------
# --battery flag parsing (spec R2)
# ---------------------------------------------------------------------------

def test_battery_flag_parsing():
    """--battery takes the battery name; default is '' (no battery)."""
    parser = rb.build_parser()
    args = parser.parse_args(["full"])
    assert args.battery == ""
    args = parser.parse_args(["full", "--battery", "battery"])
    assert args.battery == "battery"


def test_full_defaults_unchanged():
    """The full subcommand's default arg values are unchanged (the
    standard 3-case path's constants)."""
    parser = rb.build_parser()
    args = parser.parse_args(["full"])
    assert args.timeout_minutes == 75
    assert args.phase_timeout_minutes == 0
    assert args.stall_minutes == rb.DEFAULT_STALL_MINUTES
    assert args.cleanup_first is True
    assert args.batch is False
    assert args.battery == ""
    assert args.trim_history is True


def test_full_dispatch_battery_vs_standard():
    """full --battery battery dispatches to full_battery; full (no
    --battery) dispatches to the standard full_shared_kb — the battery
    enters through a NEW branch-guarded path, the standard path is
    untouched."""
    calls = []
    saved_shared = rb.full_shared_kb
    saved_battery_fn = rb.full_battery
    saved_argv = list(sys.argv)

    def _fake_shared(args):
        calls.append("shared")
        return 0

    def _fake_battery(args):
        calls.append("battery")
        return 0

    rb.full_shared_kb = _fake_shared
    rb.full_battery = _fake_battery
    try:
        sys.argv = ["run_benchmark.py", "full"]
        assert rb.main() == 0
        assert calls == ["shared"]

        calls.clear()
        sys.argv = ["run_benchmark.py", "full", "--battery", "battery"]
        assert rb.main() == 0
        assert calls == ["battery"]
    finally:
        rb.full_shared_kb = saved_shared
        rb.full_battery = saved_battery_fn
        sys.argv = saved_argv


# ---------------------------------------------------------------------------
# preflight battery-mode KB probe (spec R2)
# ---------------------------------------------------------------------------

def test_battery_kb_probe_present():
    """The probe returns count=<n> when the KB is present (count > 0)."""
    def fake_post(url, body, timeout=30.0):
        assert url.endswith("/v1/query"), url
        assert body["metta"] == rb.BATTERY_KB_PROBE_QUERY
        return {"count": 3}
    saved = rb._http_post
    rb._http_post = fake_post
    try:
        assert rb._battery_kb_probe(_args()) == "count=3"
    finally:
        rb._http_post = saved


def test_battery_kb_probe_absent():
    """The probe returns 'absent' when the KB is not present (count=0)
    — the preflight check value that FAILS the battery run."""
    def fake_post(url, body, timeout=30.0):
        return {"count": 0}
    saved = rb._http_post
    rb._http_post = fake_post
    try:
        assert rb._battery_kb_probe(_args()) == "absent"
    finally:
        rb._http_post = saved


def test_battery_kb_probe_error():
    """A probe failure (read-proxy unreachable) returns 'error: ...'."""
    def fake_post(url, body, timeout=30.0):
        raise RuntimeError("connection refused")
    saved = rb._http_post
    rb._http_post = fake_post
    try:
        out = rb._battery_kb_probe(_args())
        assert out.startswith("error:")
    finally:
        rb._http_post = saved


def test_preflight_battery_mode_wires_kb_probe_check():
    """In battery mode the preflight records the battery_kb_present
    check (dry-run wiring: the check appears in the checks dict and
    passes as 'dry-run')."""
    args = _args()
    args.dry_run = True
    saved = rb._battery_kb_probe
    rb._battery_kb_probe = lambda a: "count=3"
    try:
        out = rb.preflight(args)
        assert out == 0, "dry-run preflight must PASS"
    finally:
        rb._battery_kb_probe = saved


# ---------------------------------------------------------------------------
# no-cleanup-in-battery-mode (spec R2)
# ---------------------------------------------------------------------------

def _run_battery_stubbed(args):
    """Run full_battery with the phases stubbed to success; returns
    full_battery's exit code (the grade-case JSONs are pre-written by
    the caller)."""
    saved = {}
    stubs = {
        "preflight": lambda a: 0,
        "setup_reasoning_phase": lambda a: 0,
        "agent_case": lambda a: 0,
        "grade_case": lambda a: 0,
        "report": lambda a: 0,
        "teardown": lambda a: 0,
    }
    for name, stub in stubs.items():
        saved[name] = getattr(rb, name)
        setattr(rb, name, stub)
    # _sudo_write: the answers.md init at battery run start
    saved_write = rb._sudo_write
    rb._sudo_write = lambda path, content: True
    try:
        rc = rb.full_battery(args)
        assert rc == 0, "stubbed phases must succeed"
    finally:
        for name, stub in saved.items():
            setattr(rb, name, stub)
        rb._sudo_write = saved_write
    return rc


def test_battery_mode_skips_cleanup_das():
    """The battery mode does NOT run cleanup-das (the live KB is
    preserved — spec R2: 'in battery mode skip cleanup-das')."""
    args = _args(run_id="t-battery-nocleanup")
    cleanup_calls = []
    saved_cleanup = rb.cleanup_das
    rb.cleanup_das = lambda a: (cleanup_calls.append(1), 0)[1]
    try:
        rc = _run_battery_stubbed(args)
        assert rc == 0
        assert cleanup_calls == [], \
            "cleanup_das must not run in battery mode"
    finally:
        rb.cleanup_das = saved_cleanup


# ---------------------------------------------------------------------------
# grade.json gate_verdict computation with battery cases (spec R2)
# ---------------------------------------------------------------------------

def _write_grade_case(run_id, case_id, verdict):
    rd = rb.RESULTS_DIR / run_id
    rd.mkdir(parents=True, exist_ok=True)
    (rd / f"grade-case-{case_id}.json").write_text(
        json.dumps({"case_id": case_id, "verdict": verdict}), encoding="utf-8")


def test_battery_grade_json_gate_verdict_all_pass():
    """gate_verdict PASS iff all 5 battery cases PASS (all-pass case)."""
    args = _args(run_id="t-battery-all-pass")
    for case in facts.BATTERY_CASES:
        _write_grade_case(args.run_id, case["id"], "PASS")
    _run_battery_stubbed(args)
    g = json.loads((rb.RESULTS_DIR / args.run_id / "grade.json").read_text())
    assert g["gate_verdict"] == "PASS"
    assert g["mode"] == "battery"
    assert g["cases_passed"] == 5
    assert g["cases_total"] == 5


def test_battery_grade_json_gate_verdict_one_fail():
    """gate_verdict FAIL when any battery case FAILs (4 PASS + 1 FAIL)."""
    args = _args(run_id="t-battery-one-fail")
    verdicts = {"stars-claim": "PASS", "floor-lamp": "PASS",
                "burned-bulb": "PASS", "stv-derivation": "PASS",
                "color-probe": "FAIL"}
    for cid, verdict in verdicts.items():
        _write_grade_case(args.run_id, cid, verdict)
    _run_battery_stubbed(args)
    g = json.loads((rb.RESULTS_DIR / args.run_id / "grade.json").read_text())
    assert g["gate_verdict"] == "FAIL"
    assert g["cases_passed"] == 4
    assert g["cases_total"] == 5
