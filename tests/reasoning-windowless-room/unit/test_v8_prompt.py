"""v8 prompt contract (oc2-openclaw-native: pin-free).

2026-10-25 14:48 UTC directive (Balázs: "build the pin ledger as v8 and
restart e2e"). The pin ledger tests are REMOVED with the pin channel
(oc2-openclaw-native spec C1); the surviving tests pin the post-removal
shape: the working-memory channel (extraction record), the anti-loop
rules, and the STOP rule.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

TEMPLATE_PATH = os.path.join(HERE, "..", "agent_prompt_template.md")


def _template() -> str:
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def test_working_memory_names_extraction_record():
    # the extraction record (facts-index) is the working-memory channel
    t = _template()
    assert "{{FACTS_INDEX_PATH}}" in t
    assert "expr <the-exact-expression> top=<handle>" in t


def test_no_pin_references_in_template():
    # oc2-openclaw-native C1: the pin skill is removed; the prompt
    # templates carry NO pin/ledger references
    t = _template()
    assert "PINNED LEDGER" not in t
    assert "pin tool" not in t.lower()
    assert "pinned" not in t.lower()
    assert "PIN-SUCCESS" not in t
    assert "LEDGER:" not in t


def test_anti_loop_rules_present():
    # the anti-loop rules survive the pin removal
    t = _template()
    seg = t[t.index("**Campaign rules (anti-loop, hard):**"):t.index("### REQUIRED FORMAT")]
    assert "never re-read state files you already have in your prompt" in seg


def test_ledger_precedes_pipeline_steps():
    # the working-memory section precedes the pipeline steps
    t = _template()
    assert t.index("## TASK LIST") < t.index("1. **EXTRACT")
