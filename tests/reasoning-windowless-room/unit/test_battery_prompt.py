#!/usr/bin/env python3
"""oc3 audit mode unit tests — the mandatory live-retrieve contract
(R1, spec specs/oc3-research-audit-mode/spec.md).

The battery reasoning template (agent_battery_reasoning_prompt_template.md)
must instruct the agent to perform a LIVE das-retrieve for its QUERY
against the read-proxy BEFORE writing FACTS and to quote THAT live
receipt; the standard reasoning template stays untouched (the standard
3-case flow already carries the QUERY-first contract).

All tests are pure logic (no docker, no sudo, no network).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import facts
import run_benchmark as rb

REPO_ROOT = os.path.join(HERE, "..", "..", "..")


def _args(**kw):
    return type("Args", (), {
        "run_id": "t-battery-prompt", "case": "stars-claim",
        "battery": "battery", "timeout_minutes": 75,
        "memory_volume": "/tmp/t-battery-memvol",
        "dry_run": False,
        "agent_profile": "omega",
        "write_bridge": "http://172.20.0.5:8080",
        "read_proxy": "http://172.20.0.3:8080",
        **kw,
    })()


# ---------------------------------------------------------------------------
# the battery template carries the mandatory live-retrieve contract
# ---------------------------------------------------------------------------

def test_battery_template_file_exists():
    path = rb.HERE / rb.BATTERY_REASONING_TEMPLATE
    assert path.is_file(), f"missing battery template: {path}"


def test_battery_template_carries_live_retrieve_contract():
    text = (rb.HERE / rb.BATTERY_REASONING_TEMPLATE).read_text(
        encoding="utf-8")
    assert "MANDATORY LIVE-RETRIEVE CONTRACT" in text
    # the retrieve-before-FACTS instruction, in substance verbatim:
    # LIVE retrieve for the QUERY, in the case window, BEFORE FACTS
    assert "LIVE das-retrieve for your QUERY" in text
    assert "Before writing FACTS" in text
    assert "Retrieval precedes FACTS" in text
    # the receipt must come from the live call, never copied records
    assert "copied from ANY earlier record does NOT satisfy" in text
    assert "extraction record" in text
    assert "checkpoint manifest" in text
    # the read-proxy is the target (the endpoint the agent already uses)
    assert "read-proxy" in text


def test_rendered_battery_prompt_carries_live_retrieve_contract():
    """Acceptance R1: the RENDERED battery prompt contains the
    retrieve-before-FACTS instruction."""
    case = rb._case_by_id("stars-claim")
    rendered = rb._render_battery_reasoning_prompt(_args(), case)
    assert "MANDATORY LIVE-RETRIEVE CONTRACT" in rendered
    assert "LIVE das-retrieve for your QUERY" in rendered
    assert "Before writing FACTS" in rendered
    # fully substituted (no leftover placeholders)
    for placeholder in ("{{RUN_ID}}", "{{CASE_ID}}", "{{QUESTION}}",
                        "{{URL_LIST_PATH}}", "{{ANSWERS_PATH}}",
                        "{{FACTS_INDEX_PATH}}"):
        assert placeholder not in rendered, placeholder
    assert "t-battery-prompt" in rendered
    assert "stars-claim" in rendered
    assert case["question"] in rendered


def test_rendered_battery_prompt_keeps_the_gate_format_block():
    """The battery template must keep the gate-parsed block format
    (### CASE, QUERY, DAS_RETRIEVE_OK, FACTS, HANDLES, REASONING,
    FINAL ANSWER) — the contract is additive, the gates unchanged."""
    case = rb._case_by_id("stars-claim")
    rendered = rb._render_battery_reasoning_prompt(_args(), case)
    assert "### CASE stars-claim" in rendered
    assert "QUERY: <the exact metta pattern you executed>" in rendered
    assert "DAS_RETRIEVE_OK untrusted=true count=<n>" in rendered
    assert "FACTS:" in rendered
    assert "HANDLES:" in rendered
    assert "REASONING:" in rendered
    assert "FINAL ANSWER (stars-claim): <answer>" in rendered
    assert "Do NOT fabricate" in rendered


def test_rendered_battery_prompt_quotes_live_receipt_rule():
    """The REQUIRED FORMAT receipt rule points at the live call (the
    oc3-battery memory-answer failure mode)."""
    case = rb._case_by_id("floor-lamp")
    rendered = rb._render_battery_reasoning_prompt(_args(), case)
    assert ("copied from the output of YOUR live retrieve call in THIS "
            "case's window") in rendered
    assert "never a receipt copied from an earlier phase's records" in rendered


def test_standard_reasoning_render_has_no_live_retrieve_contract():
    """The STANDARD reasoning template (and its render) stays untouched:
    no battery contract text leaks into the standard 3-case flow."""
    args = _args(battery="")
    for case in facts.TEST_CASES:
        rendered = rb._render_reasoning_prompt(args, case)
        assert "MANDATORY LIVE-RETRIEVE CONTRACT" not in rendered, case["id"]
        assert "LIVE das-retrieve for your QUERY" not in rendered, case["id"]
    text = (rb.HERE / "agent_reasoning_prompt_template.md").read_text(
        encoding="utf-8")
    assert "MANDATORY LIVE-RETRIEVE CONTRACT" not in text


def test_setup_case_battery_mode_renders_battery_template():
    """The selection seam: phase='reasoning' + --battery renders the
    battery template; without --battery the standard template renders
    (standard 3-case flow unchanged)."""
    saved = (rb._sudo_read, rb._sudo_write, rb._sudo_run, rb._agent_restart,
             rb._prepare_benchmark_dir, rb._sweep_stale_manifests)
    writes = {}

    def fake_write(path, content, timeout=60.0):
        writes[str(path)] = content
        return True

    rb._sudo_read = lambda p: ""
    rb._sudo_write = fake_write
    rb._sudo_run = lambda cmd, timeout=60.0: type(
        "R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    rb._agent_restart = lambda profile=None: True
    rb._prepare_benchmark_dir = lambda args: None
    rb._sweep_stale_manifests = lambda args: []
    try:
        battery_case = rb._case_by_id("stars-claim")
        rc = rb.setup_case(_args(battery="battery"), phase="reasoning")
        assert rc == 0
        prompt = writes.get("prompt.txt", "")
        if not prompt:  # find the prompt write by content marker
            prompt = next((c for c in writes.values()
                           if "BENCHMARK MODE" in c), "")
        assert "MANDATORY LIVE-RETRIEVE CONTRACT" in prompt, \
            "battery mode must render the battery template"

        writes.clear()
        std_case = rb._case_by_id("original")
        rc = rb.setup_case(_args(battery="", case="original"),
                           phase="reasoning")
        assert rc == 0
        prompt = next((c for c in writes.values()
                       if "BENCHMARK MODE" in c), "")
        assert "MANDATORY LIVE-RETRIEVE CONTRACT" not in prompt, \
            "the standard flow must keep the standard template"
        assert "REASONING PHASE" in prompt
    finally:
        (rb._sudo_read, rb._sudo_write, rb._sudo_run, rb._agent_restart,
         rb._prepare_benchmark_dir, rb._sweep_stale_manifests) = saved


def test_rendered_battery_prompt_pack_prompt_override():
    """An external pack case's optional `prompt` (full prompt text
    override) replaces the question text in the rendered battery
    prompt."""
    case = {"id": "prompted-case", "question": "short question",
            "prompt": "A much longer, fully-worded research prompt."}
    rendered = rb._render_battery_reasoning_prompt(
        _args(case="prompted-case"), case)
    assert "A much longer, fully-worded research prompt." in rendered
    assert "short question" not in rendered
    assert "### CASE prompted-case" in rendered


def test_battery_template_shorter_than_fat_template():
    """Sanity: the battery template stays a lean phase prompt (same
    ballpark as the standard reasoning template, well under the fat
    template)."""
    here = rb.HERE
    fat = len((here / "agent_prompt_template.md").read_text(
        encoding="utf-8").split())
    rea = len((here / "agent_reasoning_prompt_template.md").read_text(
        encoding="utf-8").split())
    bat = len((here / rb.BATTERY_REASONING_TEMPLATE).read_text(
        encoding="utf-8").split())
    assert bat < fat // 2, f"battery template too fat: {bat} >= {fat // 2}"
    # the contract is additive: the battery template is the standard
    # reasoning template plus the contract — bounded growth only
    assert bat < rea + 350, \
        f"battery template grew too much vs the standard: {bat} vs {rea}"


def test_standard_templates_frozen_vs_origin_main():
    """R1 hard constraint: the standard prompt templates stay
    byte-identical (the contract lives ONLY in the new battery
    template)."""
    import subprocess
    for rel in ("tests/reasoning-windowless-room/agent_prompt_template.md",
                "tests/reasoning-windowless-room/"
                "agent_extraction_prompt_template.md",
                "tests/reasoning-windowless-room/"
                "agent_reasoning_prompt_template.md",
                "tests/reasoning-windowless-room/"
                "agent_extraction_prompt_template.md"):
        result = subprocess.run(["git", "diff", "origin/main", "--", rel],
                                 capture_output=True, text=True,
                                 cwd=REPO_ROOT)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", \
            f"{rel} has diffs vs origin/main:\n{result.stdout}"
