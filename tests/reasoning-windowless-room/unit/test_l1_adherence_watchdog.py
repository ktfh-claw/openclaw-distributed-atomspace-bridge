#!/usr/bin/env python3
"""L1 deltas (Balázs directive 2026-10-30 23:50 UTC): harness-side
state-vs-claim adherence cross-checks (delta 1), layer-split verdicts
(delta 2), and the stall watchdog (delta 3).

Additive harness lane — the A/Q/E/R/P mechanism gate semantics and the
existing grade-case / grade.json contracts stay pinned unchanged by the
existing suites. These tests pin the NEW lane only.

oc2-openclaw-native spec C1: the pin channel is REMOVED; the adherence
lane keeps ONLY the answers-file-based ADHERENCE_DUPLICATE_BLOCK check.
The pin-derived ADHERENCE_FALSE_COMPLETION condition is deleted with
the pin channel (no pin exists to make a false claim with).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import run_benchmark as rb


# --- live-shaped answers.md blocks ------------------------------------------

BLOCK_FALSE = (
    "### CASE false\n\nQUERY: (Evaluation (Predicate \"reveals\") "
    "(List \"looking-up-illuminated-room\" $X))\nDAS_RETRIEVE_OK "
    "untrusted=true count=1\nFINAL ANSWER (false): FALSE\n")
BLOCK_ORIGINAL = "### CASE original\n\nQUERY: (x)\nFINAL ANSWER (original): yes\n"


# --- delta 1: classify_adherence (state-vs-claim) -------------------------

def test_classify_duplicate_block():
    # wr3q live class: two blocks for the case (last-wins grading hides
    # the discipline breach from the mechanism gate).
    conds = rb.classify_adherence("false", BLOCK_FALSE + "\n" + BLOCK_FALSE)
    assert conds == ["ADHERENCE_DUPLICATE_BLOCK"], conds


def test_classify_consistent_terminal_clean():
    conds = rb.classify_adherence("false", BLOCK_FALSE)
    assert conds == [], conds


def test_classify_no_block_clean():
    # No block for the case -> no adherence conditions (the timeout lane
    # covers the incomplete case; the pin channel is gone).
    assert rb.classify_adherence("false", BLOCK_ORIGINAL) == []


# --- delta 2: layer-split fields -------------------------------------------

def test_layer_split_fields_shape():
    fields = rb._layer_split_fields(
        "PASS", ["Q_ATTESTED_VIA_ACCESS_LOG"],
        {"conditions": [], "evidence": {"block_count": 1}})
    assert fields["mechanism_verdict"] == "PASS"
    assert fields["mechanism_conditions"] == ["Q_ATTESTED_VIA_ACCESS_LOG"]
    assert fields["adherence_conditions"] == []
    assert fields["adherence_evidence"] == {"block_count": 1}


# --- delta 3: stall watchdog ------------------------------------------------

def test_watchdog_triggers_after_quiet_window():
    w = rb.StallWatchdog(stall_minutes=15, now=0.0)
    assert not w.should_abort(now=899.0)
    assert w.should_abort(now=901.0)


def test_watchdog_register_resets():
    w = rb.StallWatchdog(stall_minutes=15, now=0.0)
    w.register(moved=True, now=600.0)
    assert not w.should_abort(now=1400.0)
    assert w.should_abort(now=1501.0)


def test_watchdog_quiet_register_does_not_reset():
    w = rb.StallWatchdog(stall_minutes=15, now=100.0)
    w.register(moved=False, now=200.0)
    assert w.should_abort(now=100.0 + 901.0)


def test_default_stall_minutes():
    # Raised 15 -> 25 (smoke-20261103f false-case RCA, 2026-11-04):
    # observed extraction paces run 10-20 min without a persist receipt
    # (manifest-only forward signal); 15 min aborted healthy turns.
    assert rb.DEFAULT_STALL_MINUTES == 25
