#!/usr/bin/env python3
"""oc3 audit mode unit tests — the faithfulness judge (R3, spec
specs/oc3-research-audit-mode/spec.md).

Covers faithfulness_judge.py (the NEW judge prompt template; llm_judge's
transport reused, never modified) and the run_benchmark judge-selection
seam (_case_judge_fn):
- prompt shape: ONE user message, question + presented evidence + answer,
  the faithfulness question, TRUE/FALSE reply contract
- prompt isolation: no expected-answer framing (no ground truth exists)
- verdict parsing + retry/fail-safe behavior (stubbed HTTP)
- selection: a case WITH expected_answer keeps the existing judge
  EXACTLY; a case WITHOUT expected_answer gets the faithfulness judge
  with the presented evidence (FACTS/REASONING lines) injected at the
  wiring seam; dry-run wires no judge

All tests are pure logic (monkeypatched IO — no network).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import faithfulness_judge as fj
import llm_judge
import run_benchmark as rb
from grading import parse_answers_v2

_ENV_VARS = ("ASIONE_API_KEY", "OPENAI_API_KEY", "WR_JUDGE_API_KEY")


def _clear_env():
    return {v: os.environ.pop(v, None) for v in _ENV_VARS}


def _restore_env(saved):
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


def _args(**kw):
    return type("Args", (), {
        "run_id": "t-faith", "case": "open-question", "battery": "",
        "dry_run": False,
        "judge_base_url": "https://judge.invalid/v1",
        "judge_model": "test-model",
        "judge_api_key": "test-key",
        "judge_timeout": 5.0,
        **kw,
    })()


def _no_answer_case():
    """A research case with NO expected_answer (faithfulness path)."""
    return {"id": "open-question",
            "question": "Which stored knowledge supports the look-up answer?"}


def _expected_case():
    return {"id": "room-parts", "question": "What parts does a room have?",
            "expected_answer": "Walls, a floor, and a ceiling."}


def _block():
    text = ("### CASE open-question\n\n"
            'QUERY: (Inheritance $X (Concept "ceiling"))\n'
            "DAS_RETRIEVE_OK untrusted=true count=1 truncated=false results=[]\n"
            'FACTS: (Inheritance (Concept "ceiling") (Concept "opaque-surface"))\n'
            "HANDLES: h1\n"
            'REASONING: (Inheritance $X (Concept "ceiling")); '
            '(Inheritance (Concept "ceiling") (Concept "opaque-surface"))\n'
            "FINAL ANSWER (open-question): the ceiling is opaque\n")
    return parse_answers_v2(text)["open-question"]


# ---------------------------------------------------------------------------
# the NEW prompt template (build_faithfulness_messages)
# ---------------------------------------------------------------------------

def test_faithfulness_prompt_is_single_user_message():
    msgs = fj.build_faithfulness_messages(
        {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"},
        "the ceiling is opaque")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_faithfulness_prompt_contains_question_evidence_and_answer():
    case = {**_no_answer_case(),
            fj.PRESENTED_EVIDENCE_KEY:
                'FACTS: (Inheritance (Concept "ceiling") (Concept "opaque-surface"))\n'
                'REASONING: (Inheritance $X (Concept "ceiling"))'}
    ans = "the ceiling is opaque"
    content = fj.build_faithfulness_messages(case, ans)[0]["content"]
    assert case["question"] in content
    assert "(Inheritance (Concept \"ceiling\") (Concept \"opaque-surface\"))" in content
    assert "REASONING: (Inheritance $X" in content
    assert ans in content
    # each appears exactly once (no duplicated evidence injection)
    assert content.count(case["question"]) == 1
    assert content.count(ans) == 1


def test_faithfulness_prompt_asks_the_faithfulness_question():
    """The R3 judge question, verbatim in substance: does the answer
    follow strictly from the presented facts without inventing facts?"""
    content = fj.build_faithfulness_messages(
        {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"},
        "an answer")[0]["content"]
    assert "Given ONLY the facts the agent presented" in content
    assert "strictly supported by those facts" in content
    assert "without inventing facts that are not in the presented set" in content
    assert "Reply with exactly one word: TRUE or FALSE" in content


def test_faithfulness_prompt_has_no_expected_answer_framing():
    """No ground truth exists for research questions — the prompt must
    not carry the expected-answer judge's framing."""
    content = fj.build_faithfulness_messages(
        {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"},
        "an answer")[0]["content"]
    assert "Expected correct answer" not in content
    assert "expected" not in content.lower()


def test_faithfulness_prompt_is_not_the_expected_answer_template():
    """The existing judge prompt (llm_judge.build_messages) and the
    faithfulness template are DIFFERENT prompts."""
    case = _no_answer_case()
    old = llm_judge.build_messages(case, "an answer")[0]["content"]
    new = fj.build_faithfulness_messages(
        {**case, fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"},
        "an answer")[0]["content"]
    assert old != new
    assert "faithful" in new
    assert "faithful" not in old


# ---------------------------------------------------------------------------
# the judge callable (frozen llm_judge transport, stubbed HTTP)
# ---------------------------------------------------------------------------

def _stub_chat(reply, calls=None):
    def _chat(base_url, model, api_key, messages, timeout):
        if calls is not None:
            calls.append({"base_url": base_url, "model": model,
                          "key": api_key, "messages": messages})
        return reply
    return _chat


def test_faithfulness_judge_true_verdict():
    saved = _clear_env()
    saved_chat = llm_judge._chat
    try:
        llm_judge._chat = _stub_chat("TRUE. The answer restates the presented facts.")
        judge = fj.make_faithfulness_judge(api_key="k")
        case = {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"}
        ok, detail = judge(case, "an answer")
        assert ok is True
        assert detail["judge_verdict"] == "TRUE"
        assert detail["judge_mode"] == "faithfulness"
    finally:
        llm_judge._chat = saved_chat
        _restore_env(saved)


def test_faithfulness_judge_false_verdict():
    saved = _clear_env()
    saved_chat = llm_judge._chat
    try:
        llm_judge._chat = _stub_chat("FALSE — the answer invents a new fact.")
        judge = fj.make_faithfulness_judge(api_key="k")
        case = {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"}
        ok, detail = judge(case, "an answer")
        assert ok is False
        assert detail["judge_verdict"] == "FALSE"
        assert detail["judge_mode"] == "faithfulness"
    finally:
        llm_judge._chat = saved_chat
        _restore_env(saved)


def test_faithfulness_judge_sends_the_faithfulness_prompt():
    saved = _clear_env()
    saved_chat = llm_judge._chat
    calls = []
    try:
        llm_judge._chat = _stub_chat("TRUE", calls)
        judge = fj.make_faithfulness_judge(base_url="https://judge.invalid/v1",
                                           model="m1", api_key="k1")
        case = {**_no_answer_case(),
                fj.PRESENTED_EVIDENCE_KEY: "FACTS: (presented)"}
        judge(case, "the answer")
        assert len(calls) == 1
        assert calls[0]["base_url"] == "https://judge.invalid/v1"
        assert calls[0]["model"] == "m1"
        assert calls[0]["key"] == "k1"
        content = calls[0]["messages"][0]["content"]
        assert "Given ONLY the facts the agent presented" in content
        assert "FACTS: (presented)" in content
    finally:
        llm_judge._chat = saved_chat
        _restore_env(saved)


def test_faithfulness_judge_retries_transient_http_once():
    saved = _clear_env()
    saved_chat = llm_judge._chat
    saved_sleep = llm_judge.RETRY_SLEEP_S
    attempts = []

    def flaky(base_url, model, api_key, messages, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient network error")
        return "TRUE"

    try:
        llm_judge.RETRY_SLEEP_S = 0
        llm_judge._chat = flaky
        judge = fj.make_faithfulness_judge(api_key="k")
        case = {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"}
        ok, _ = judge(case, "an answer")
        assert ok is True
        assert len(attempts) == 2
    finally:
        llm_judge._chat = saved_chat
        llm_judge.RETRY_SLEEP_S = saved_sleep
        _restore_env(saved)


def test_faithfulness_judge_unavailable_after_retries():
    saved = _clear_env()
    saved_chat = llm_judge._chat
    saved_sleep = llm_judge.RETRY_SLEEP_S
    try:
        llm_judge.RETRY_SLEEP_S = 0

        def down(base_url, model, api_key, messages, timeout):
            raise RuntimeError("api down")

        llm_judge._chat = down
        judge = fj.make_faithfulness_judge(api_key="k")
        case = {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"}
        try:
            judge(case, "an answer")
            raise AssertionError("expected JudgeUnavailable")
        except llm_judge.JudgeUnavailable as e:
            assert "faithfulness judge call failed" in str(e)
            assert "api down" in str(e)
    finally:
        llm_judge._chat = saved_chat
        llm_judge.RETRY_SLEEP_S = saved_sleep
        _restore_env(saved)


def test_faithfulness_judge_unparseable_reply_raises():
    saved = _clear_env()
    saved_chat = llm_judge._chat
    try:
        llm_judge._chat = _stub_chat("maybe, hard to say")
        judge = fj.make_faithfulness_judge(api_key="k")
        case = {**_no_answer_case(), fj.PRESENTED_EVIDENCE_KEY: "FACTS: (a)"}
        try:
            judge(case, "an answer")
            raise AssertionError("expected JudgeUnavailable")
        except llm_judge.JudgeUnavailable:
            pass
    finally:
        llm_judge._chat = saved_chat
        _restore_env(saved)


def test_faithfulness_judge_without_key_raises_unavailable():
    saved = _clear_env()
    try:
        try:
            fj.make_faithfulness_judge(
                api_key="", runtime_env_path="/nonexistent/runtime.env")
            raise AssertionError("expected JudgeUnavailable")
        except llm_judge.JudgeUnavailable:
            pass
    finally:
        _restore_env(saved)


# ---------------------------------------------------------------------------
# the selection seam (run_benchmark._case_judge_fn)
# ---------------------------------------------------------------------------

def _stub_getters(expected=None, faithfulness=None):
    """Stub both judge getters with sentinels; returns (saved, sentinels)."""
    sent = {
        "expected": expected if expected is not None else
            (lambda case, ans: (True, {"stub": "expected"})),
        "faith": faithfulness if faithfulness is not None else
            (lambda case, ans: (True, {"stub": "faithfulness"})),
    }
    saved = (rb._get_judge, rb._get_faithfulness_judge)
    rb._get_judge = lambda a: sent["expected"]
    rb._get_faithfulness_judge = lambda a: sent["faith"]
    return saved, sent


def test_selection_expected_answer_case_keeps_existing_judge():
    """A case WITH an expected_answer keeps the existing A-gate judge
    EXACTLY — the seam returns _get_judge's callable verbatim."""
    saved, sent = _stub_getters()
    try:
        judge = rb._case_judge_fn(_args(), _expected_case(), _block())
        assert judge is sent["expected"]
    finally:
        rb._get_judge, rb._get_faithfulness_judge = saved


def test_selection_no_expected_answer_case_gets_faithfulness():
    """A case WITHOUT an expected_answer is judged by the faithfulness
    judge; the presented evidence is injected into its case dict."""
    seen = {}

    def faith(case, ans):
        seen["case"] = case
        seen["ans"] = ans
        return True, {"judge_mode": "faithfulness"}

    saved, sent = _stub_getters(faithfulness=faith)
    try:
        judge = rb._case_judge_fn(_args(), _no_answer_case(), _block())
        assert judge is not sent["faith"], \
            "the seam wraps the judge (evidence injection), it does not" \
            " return it raw"
        ok, detail = judge(_no_answer_case(), "the ceiling is opaque")
        assert ok is True
        assert detail["judge_mode"] == "faithfulness"
        # the judge's case dict carries the presented evidence...
        assert seen["case"][fj.PRESENTED_EVIDENCE_KEY] == \
            ('FACTS: (Inheritance (Concept "ceiling") '
             '(Concept "opaque-surface"))\n'
             'REASONING: (Inheritance $X (Concept "ceiling")); '
             '(Inheritance (Concept "ceiling") (Concept "opaque-surface"))')
        # ...and the question (context), but no invented expected answer
        assert seen["case"]["question"] == _no_answer_case()["question"]
        assert "expected_answer" not in seen["case"]
        assert seen["ans"] == "the ceiling is opaque"
    finally:
        rb._get_judge, rb._get_faithfulness_judge = saved


def test_selection_faithfulness_missing_block_is_empty_evidence():
    """A missing answers block still wires a judge (grade_answer's
    A_MISSING fires before the judge call — but the seam must not
    crash); the presented evidence is ''."""
    seen = {}

    def faith(case, ans):
        seen["case"] = case
        return False, {"judge_mode": "faithfulness"}

    saved, _sent = _stub_getters(faithfulness=faith)
    try:
        judge = rb._case_judge_fn(_args(), _no_answer_case(), None)
        judge(_no_answer_case(), "an answer")
        assert seen["case"][fj.PRESENTED_EVIDENCE_KEY] == ""
    finally:
        rb._get_judge, rb._get_faithfulness_judge = saved


def test_selection_dry_run_wires_no_judge():
    """Dry-run wires no judge (both getters return None; grade_answer
    would emit A_JUDGE_UNAVAILABLE — grade-case dry-runs earlier)."""
    args = _args(dry_run=True)
    assert rb._case_judge_fn(args, _no_answer_case(), _block()) is None
    # expected-answer cases keep _get_judge's dry-run None too
    assert rb._case_judge_fn(args, _expected_case(), _block()) is None


def test_selection_works_through_grade_answer_paths():
    """End-to-end through grading.grade_answer: the faithfulness judge's
    TRUE/FALSE maps to pass/A_WRONG exactly like the existing judge."""
    import grading

    def faith(case, ans):
        return (ans == "the ceiling is opaque",
                {"judge_mode": "faithfulness"})

    saved, _sent = _stub_getters(faithfulness=faith)
    try:
        judge = rb._case_judge_fn(_args(), _no_answer_case(), _block())
        conds, detail = grading.grade_answer(_no_answer_case(),
                                             "the ceiling is opaque", judge)
        assert conds == []
        assert detail["judge"]["judge_mode"] == "faithfulness"
        conds, _ = grading.grade_answer(_no_answer_case(),
                                        "the sky and the stars", judge)
        assert conds == ["A_WRONG"]
    finally:
        rb._get_judge, rb._get_faithfulness_judge = saved


def test_llm_judge_file_is_frozen_untouched():
    """R3 hard constraint: llm_judge.py stays byte-identical (vs
    origin/main, the established diff-free pattern) — the faithfulness
    judge must reuse it, never edit it."""
    import subprocess
    repo_root = os.path.join(HERE, "..", "..", "..")
    rel = "tests/reasoning-windowless-room/llm_judge.py"
    result = subprocess.run(["git", "diff", "origin/main", "--", rel],
                            capture_output=True, text=True, cwd=repo_root)
    assert result.returncode == 0, f"git diff failed: {result.stderr}"
    assert result.stdout.strip() == "", \
        f"llm_judge.py has diffs vs origin/main:\n{result.stdout}"
