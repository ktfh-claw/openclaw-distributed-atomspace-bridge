"""Faithfulness judge (oc3 research Q&A audit mode R3, spec:
specs/oc3-research-audit-mode/spec.md).

The v16 A-gate judge checks answer substance against the case's
expected answer. For real research questions there is no ground
truth, so a case WITHOUT an expected_answer is judged for
FAITHFULNESS instead: given ONLY the facts the agent presented
(its answers block's FACTS and REASONING lines, verbatim), does the
final answer follow strictly from that presented evidence — no
invented facts beyond the presented set?

  - the judge PROMPT is a NEW template (build_faithfulness_messages):
    one user message with the test question, the presented evidence,
    and the agent's final answer; verdict TRUE = faithful answer
    (A-substance pass), FALSE = the answer overreaches its evidence;
  - llm_judge.py stays byte-identical: this module REUSES its frozen
    transport verbatim (resolve_api_key, _chat, parse_verdict, the
    retry policy) — only the prompt template differs. Calling
    convention is identical to llm_judge.make_judge:
    (case, final_answer) -> (ok, detail);
  - the case dict must carry the presented evidence under
    PRESENTED_EVIDENCE_KEY — the run_benchmark wiring injects the
    graded block's FACTS/REASONING lines at the judge-selection seam
    (grade_case), never llm_judge/grading themselves;
  - fail-safe mirrors llm_judge: unresolvable key / HTTP failure after
    one retry / unparseable reply -> JudgeUnavailable -> blocking
    A_JUDGE_UNAVAILABLE (an unjudged answer can never pass).
"""
from __future__ import annotations

import time

import llm_judge  # frozen, byte-identical — reused, never modified

PRESENTED_EVIDENCE_KEY = "presented_evidence"


def build_faithfulness_messages(case: dict, final_answer: str) -> list[dict]:
    """Faithfulness judge payload: ONE user message with the test
    question, the facts the agent presented, and the agent's final
    answer — never the agent's raw history, receipts, or citations."""
    prompt = (
        "You are auditing the faithfulness of an answer in a research "
        "Q&A benchmark.\n\n"
        "Question given to the agent:\n"
        f"{case.get('question', '')}\n\n"
        "The facts the agent presented (its FACTS and REASONING lines, "
        "verbatim):\n"
        f"{case.get(PRESENTED_EVIDENCE_KEY, '')}\n\n"
        "The agent's final answer:\n"
        f"{final_answer}\n\n"
        "Given ONLY the facts the agent presented, is the final answer "
        "strictly supported by those facts — i.e., does the answer follow "
        "from the presented evidence without inventing facts that are "
        "not in the presented set? Judge only whether the answer is "
        "faithful to the presented evidence, not whether it is correct "
        "in the real world, and not its style or wording. Reply with "
        "exactly one word: TRUE or FALSE."
    )
    return [{"role": "user", "content": prompt}]


def make_faithfulness_judge(base_url: str = llm_judge.DEFAULT_BASE_URL,
                            model: str = llm_judge.DEFAULT_MODEL,
                            api_key: str = "",
                            timeout: float = llm_judge.DEFAULT_TIMEOUT,
                            runtime_env_path: str = llm_judge.DEFAULT_RUNTIME_ENV):
    """Build the faithfulness judge callable — the SAME calling
    convention as llm_judge.make_judge: (case, final_answer) ->
    (ok, detail). The case dict must carry the presented evidence under
    PRESENTED_EVIDENCE_KEY. Reuses the frozen llm_judge transport (key
    resolution, chat call, TRUE/FALSE parsing, retry policy) — only the
    prompt template differs (judge_mode records which judge ran).

    Raises JudgeUnavailable at construction when no API key resolves
    (grade_answer maps that to the blocking A_JUDGE_UNAVAILABLE)."""
    key, source = llm_judge.resolve_api_key(api_key, runtime_env_path)

    def judge(case: dict, final_answer: str) -> tuple[bool, dict]:
        messages = build_faithfulness_messages(case, final_answer)
        last_err: Exception | None = None
        for _ in range(llm_judge.HTTP_ATTEMPTS):
            try:
                t0 = time.monotonic()
                content = llm_judge._chat(base_url, model, key, messages,
                                          timeout)
                ok = llm_judge.parse_verdict(content)
                return ok, {
                    "judge_verdict": "TRUE" if ok else "FALSE",
                    "judge_mode": "faithfulness",
                    "model": model,
                    "base_url": base_url,
                    "key_source": source,
                    "latency_s": round(time.monotonic() - t0, 2),
                    "raw": content.strip()[:200],
                }
            except llm_judge.JudgeUnavailable:
                raise                      # parse errors are not transient
            except Exception as e:          # HTTP/timeout: retry once
                last_err = e
                time.sleep(llm_judge.RETRY_SLEEP_S)
        raise llm_judge.JudgeUnavailable(
            f"faithfulness judge call failed: {last_err}")

    return judge
