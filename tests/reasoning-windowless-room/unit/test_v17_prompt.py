#!/usr/bin/env python3
"""v17 prompt template tests (oc2-openclaw-native: pin-free).

The fat template (agent_prompt_template.md) is the per-case prompt for
the sequential flow. The oc2-openclaw-native spec C1 removes the pin
skill and ALL pin/ledger references from the prompt templates; these
tests pin the post-removal shape: the answers-block grammar, the
FACTS/HANDLES copy rules, the REASONING first-step discipline, and the
wr3o/wr3p/wr3q lessons that survive the pin removal.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import run_benchmark as rb


def _template() -> str:
    return (Path(rb.HERE) / "agent_prompt_template.md").read_text(
        encoding="utf-8")


def _segment(template: str, start: str, end: str) -> str:
    i = template.index(start)
    j = template.index(end)
    return template[i:j]


def test_placeholders_all_present():
    # run_benchmark.py substitutes exactly these six
    t = _template()
    for ph in ("{{RUN_ID}}", "{{CASE_ID}}", "{{QUESTION}}",
               "{{URL_LIST_PATH}}", "{{ANSWERS_PATH}}", "{{FACTS_INDEX_PATH}}"):
        assert ph in t, ph


def test_url_list_stays_the_reference_vocabulary():
    # urls.txt remains the agent's source-url vocabulary (D5)
    t = _template()
    assert t.count("{{URL_LIST_PATH}}") >= 2


def test_ledger_stop_final_answer_retained():
    # the surviving discipline sections are untouched by the slim
    t = _template()
    assert "## STOP rule" in t
    assert "FINAL ANSWER ({{CASE_ID}}): <answer>" in t


def test_no_pin_references_in_template():
    # oc2-openclaw-native C1: the pin skill is removed; the prompt
    # templates carry NO pin/ledger references
    t = _template()
    assert "PINNED LEDGER" not in t
    assert "pin tool" not in t.lower()
    assert "pinned" not in t.lower()
    assert "PIN-SUCCESS" not in t
    assert "LEDGER:" not in t


def test_rendered_prompt_paths_per_profile():
    # the rendered prompt carries the profile-specific paths
    args = SimpleNamespace(run_id="t-run", case="original", dry_run=False,
                           memory_volume="/fake/vol", trim_history=True,
                           timeout_minutes=75)
    cases = rb._facts_mod().TEST_CASES
    for case in cases:
        rendered = rb._render_case_prompt(args, case)
        assert "{{" not in rendered, \
            f"unrendered placeholder survives in case {case['id']}"
        assert "FINAL ANSWER ({{CASE_ID}})" not in rendered


# ---------------------------------------------------------------------------
# render: every case prompt renders with the HANDLES line
# ---------------------------------------------------------------------------

def _render(case) -> str:
    args = SimpleNamespace(run_id="t-run", case=case["id"], dry_run=False,
                           memory_volume="/fake/vol", trim_history=True,
                           timeout_minutes=75)
    return rb._render_case_prompt(args, case)


def test_rendered_prompt_carries_v17_contract_for_every_case():
    # a dry-run of `full` renders the prompt with the HANDLES line and
    # the v3 add-atom form, for every case in TEST_CASES
    cases = rb._facts_mod().TEST_CASES
    assert cases
    for case in cases:
        rendered = _render(case)
        assert "{{" not in rendered, \
            f"unrendered placeholder survives in case {case['id']}"
        assert ("HANDLES: <the atom handles of the FACTS expressions, in the "
                "same order") in rendered, case["id"]
        assert ('(metta "(add-atom &persistent (<expression>) \\"<source-url>\\" '
                '(stv 0.9 0.8))")') in rendered, case["id"]
        assert "expr <the-exact-expression> top=<handle>" in rendered, case["id"]


# ---------------------------------------------------------------------------
# wr3o lessons (2026-10-28 live run): two agent-discipline failures the
# prompt must prevent at the source — R_NOT_METTA from a bracketed probe
# annotation in REASONING (unsolvable) and the E_FACTS_NOT_IN_INDEX +
# H_MISMATCH pair from unwrapping a recorded expression while keeping its
# receipt handle (false case)
# ---------------------------------------------------------------------------

def test_step4_bans_bracket_annotations_in_reasoning():
    # unsolvable case: a `[reverse-direction probe count=0]` bracket note
    # inside REASONING is prose under the strict gate (R_NOT_METTA)
    seg = _segment(_template(), "4. **EXECUTE", "5. **WRITE")
    assert "NEVER annotate anything inside REASONING" in seg
    assert "bracketed notes" in seg
    assert "`R_NOT_METTA`" in seg
    # the zero-count evidence rides in the block's receipt line, not REASONING
    assert "DAS_RETRIEVE_OK ... count=0" in seg
    assert "never a note in REASONING" in seg


def test_gate_rule_reasoning_brackets_are_prose():
    # the block's REASONING gate rule carries the same ban
    fmt = _segment(_template(), "### REQUIRED FORMAT", "## Write artifacts")
    assert "Bracketed annotations are prose too" in fmt


def test_step5_facts_wrapper_preservation():
    # false case: unwrapping `(Concept "...")` type wrappers from a recorded
    # expression rewrites it — the rewritten form was never recorded and the
    # receipt handle paired with it belongs to the original form
    seg = _segment(_template(), "5. **WRITE", "### REQUIRED FORMAT")
    assert ("type wrappers such as `(Concept \"...\")` inside a stored "
            "expression are PART of the expression") in seg
    assert "Unwrapping, simplifying, or re-formatting a recorded expression rewrites it" in seg
    assert "`E_FACTS_NOT_IN_INDEX`" in seg
    assert "`H_MISMATCH`" in seg


def test_step5_handles_pair_copy_rule():
    # the recorded `expr <expression> top=<handle>` line pairs an expression
    # with its handle — the pair must survive to the block intact
    seg = _segment(_template(), "5. **WRITE", "### REQUIRED FORMAT")
    assert "A handle is valid ONLY with the exact expression it was issued for" in seg
    assert "copy the PAIR intact" in seg


def test_gate_rules_facts_and_handles_pair_discipline():
    fmt = _segment(_template(), "### REQUIRED FORMAT", "## Write artifacts")
    # FACTS bullet: the recorded form is the claim — wrappers and all
    assert "The recorded form is the claim — wrappers and all" in fmt
    # HANDLES bullet: the handle travels together with its expression
    assert "Copy each handle TOGETHER with its expression" in fmt


# ---------------------------------------------------------------------------
# wr3p lesson (2026-10-28 live run): unsolvable step-0 verbatim discipline.
# The agent wrote trace step 0 as the question clause WRAPPED in a
# hand-annotated absence truth value `(( QUERY ) (stv 0.0 0.9))`; the gate
# matches the first trace step against the executed QUERY (grading.py
# R_TRACE_NOT_GROUNDED fires BEFORE the unsolvable index-grounding
# exemption), so a rewritten first step fails the whole case. The prompt
# must make the bare-first-step discipline explicit.
# ---------------------------------------------------------------------------

def test_step4_unsolvable_trace_opens_with_bare_question_clause():
    # step 4: the trace's FIRST step is the question clause EXACTLY as
    # executed — identical to the QUERY: line, no stv pair, no wrapper
    seg = _segment(_template(), "4. **EXECUTE", "5. **WRITE")
    assert "the question clause EXACTLY as you executed it" in seg
    assert "identical to the `QUERY:` line" in seg
    assert "NO `(stv ...)` pair attached" in seg
    assert "NO wrapping parentheses" in seg
    assert "`R_TRACE_NOT_GROUNDED`" in seg
    # the absence probe's stv output belongs in exec lines, never on step 0
    assert "never a wrapper on the first trace step" in seg


def test_gate_rule_reasoning_first_step_is_bare_query():
    # the block's REASONING gate rule carries the same bare-first-step
    # discipline (wr3p lesson named)
    fmt = _segment(_template(), "### REQUIRED FORMAT", "## Write artifacts")
    assert "the bare clause exactly as it stands on your `QUERY:` line" in fmt
    assert "never wrapped in an extra parenthesis layer" in fmt
    assert "never carrying an attached `(stv ...)` pair" in fmt
    assert "wr3p lesson" in fmt
    assert "failed the whole case" in fmt


def test_gate_rule_unsolvable_trace_still_opens_with_query():
    # the unsolvable bullet: probes' stv outputs stay in exec lines
    fmt = _segment(_template(), "### REQUIRED FORMAT", "## Write artifacts")
    assert "The trace still opens with the bare executed question clause" in fmt
    assert "stays in the exec lines, never on the question clause" in fmt


def test_rendered_prompt_carries_wr3p_step0_discipline_for_every_case():
    # the discipline renders for every case and introduces no banned
    # vocabulary
    cases = rb._facts_mod().TEST_CASES
    assert cases
    for case in cases:
        rendered = _render(case)
        assert "the question clause EXACTLY as you executed it" in rendered, case["id"]
        assert "never carrying an attached `(stv ...)` pair" in rendered, case["id"]
        assert "The trace still opens with the bare executed question clause" in rendered, case["id"]
        assert "provenance" not in rendered.lower(), case["id"]
        assert "archive" not in rendered.lower(), case["id"]
        assert "SOURCES" not in rendered, case["id"]
        assert "git:" not in rendered, case["id"]
        assert "sha256" not in rendered, case["id"]


def test_rendered_prompt_carries_wr3o_lessons_for_every_case():
    # the discipline additions render for every case and introduce no
    # banned vocabulary
    cases = rb._facts_mod().TEST_CASES
    assert cases
    for case in cases:
        rendered = _render(case)
        assert "NEVER annotate anything inside REASONING" in rendered, case["id"]
        assert "copy the PAIR intact" in rendered, case["id"]
        assert ("type wrappers such as `(Concept \"...\")`" in rendered), case["id"]
        assert "provenance" not in rendered.lower(), case["id"]
        assert "archive" not in rendered.lower(), case["id"]
        assert "SOURCES" not in rendered, case["id"]
        assert "git:" not in rendered, case["id"]
        assert "sha256" not in rendered, case["id"]
