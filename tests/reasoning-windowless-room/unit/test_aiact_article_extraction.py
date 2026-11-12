#!/usr/bin/env python3
"""aiact per-article extraction tests (campaign tick 5/6 —
memory/ai-act-extraction-20261112).

The single whole-corpus extraction turn overflowed the SUT session
window (live-fire evidence 2026-11-12 01:19 UTC: ~190k tokens of article
text on top of a ~109k-token prompt -> context-overflow cascade,
degenerate repetitive output, 12 consecutive unescaped-quote
BRIDGE-PERSIST-WRITE-FAILED). The redesign: ONE delivery turn PER
ARTICLE — fresh session wr-<run_id>-extract-aNN, prompt scoped to that
article, facts-index carry-over, per-article ARTICLE-COMPLETE manifest
line as the turn boundary.

Covered here:
- the per-phase delivery session key gains per-article keys;
- the per-article prompt render (article scope, provenance URL,
  escaping hardening, ARTICLE-COMPLETE line, path remap);
- the whole-corpus aiact render is unchanged when no article is bound;
- the per-article checkpoint poll (content predicate + stall re-issue);
- the article orchestrator (subset filter, records, namespace restore);
- setup_case per-article mode never re-inits the facts-index and never
  sweeps the accumulating manifest mid-run;
- full_shared_kb wiring + the per-article completion gate verdict.

All tests are pure logic (monkeypatched IO — no docker, no sudo, no
network).
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import run_benchmark as rb

PACK_PATH = str(rb.HERE / "battery" / "aiact" / "question-pack.json")


def _args(**kw):
    """An args namespace with the fields the aiact per-article paths read."""
    base = {
        "run_id": "t-run", "case": "extract", "dry_run": False,
        "agent_profile": "openclaw", "memory_volume": "/fake/vol",
        "timeout_minutes": 75, "trim_history": True, "force": False,
        "stall_minutes": 0, "phase_timeout_minutes": 0,
        "corpus": "aiact", "battery": PACK_PATH,
        "extraction_only": True, "articles": "",
        "write_bridge": "http://172.20.0.5:8080",
        "read_proxy": "http://172.20.0.3:8080",
        "provenance_repo": "/home/ubuntu/omega-provenance",
    }
    base.update(kw)
    return SimpleNamespace(**{k: v for k, (v) in base.items()})


# ---------------------------------------------------------------------------
# delivery session keys
# ---------------------------------------------------------------------------

def test_delivery_session_key_per_article():
    """aiact per-article turns get their own session key: the per-article
    pseudo-case id IS the session key (wr-<run_id>-extract-aNN); the
    whole-corpus extraction keeps 'extract'; reasoning keeps oc2 C6."""
    assert rb._delivery_session_key("extract-a01", "extraction") == \
        "extract-a01"
    assert rb._delivery_session_key("extract-a15", "extraction") == \
        "extract-a15"
    assert rb._delivery_session_key(rb.EXTRACT_PSEUDO_CASE,
                                    "extraction") == "extract"
    assert rb._delivery_session_key("original", None) == "case-original"
    # the delivery command carries the per-article session id
    args = _args(run_id="aiact-extract-x", case="extract-a07")
    cmd = rb._delivery_command(args, rb._delivery_session_key(
        args.case, "extraction"))
    assert cmd[cmd.index("--session-id") + 1] == \
        "wr-aiact-extract-x-extract-a07"


# ---------------------------------------------------------------------------
# per-article prompt rendering
# ---------------------------------------------------------------------------

def test_render_aiact_article_prompt():
    """The per-article render scopes the turn to ONE article: file, stem,
    provenance URL, the escaping hardening (tick-5 evidence: 12
    consecutive unescaped-quote persist failures), the ARTICLE-COMPLETE
    boundary line, the pack questions as context, and the openclaw
    profile path remap."""
    args = _args(article_file="article-01.md",
                 article_url=f"{rb.AIACT_SOURCE_URL_BASE}/article-01.md")
    text = rb._render_extraction_prompt(args, None)
    # the per-article template was used, fully substituted
    assert "THIS turn's scope" in text
    for token in ("{{RUN_ID}}", "{{ALL_QUESTIONS}}", "{{URL_LIST_PATH}}",
                  "{{FACTS_INDEX_PATH}}", "{{ARTICLE_FILE}}",
                  "{{ARTICLE_URL}}", "{{ARTICLE_STEM}}"):
        assert token not in text, f"unsubstituted: {token}"
    assert "article-01.md" in text and "article-01" in text
    assert f"{rb.AIACT_SOURCE_URL_BASE}/article-01.md" in text
    # escaping hardening carries the tick-5 failure evidence + the rule
    assert "expected one balanced expression after &persistent" in text
    assert '\\"' in text
    assert "One das-write call per predicate" in text
    # the boundary line the harness polls
    assert rb.AIACT_ARTICLE_COMPLETE_PREFIX in text
    assert f"ARTICLE-COMPLETE: article-01" in text
    # openclaw profile remap (workspace + benchmark-relative paths)
    assert "/var/openclaw/workspace" in text
    assert "/PeTTa/repos/Omega/memory" not in text
    # the pack questions are the extraction context
    pack = rb._load_battery_pack(PACK_PATH)
    for c in pack["cases"][:3]:
        assert c["question"][:60] in text
    # idempotency: the first action checks the manifest for THIS article
    assert "ALREADY done" in text


def test_render_aiact_article_prompt_no_other_article_leak():
    """The per-article render must not name any OTHER article file (the
    turn scope is exactly one article; cross-article dedup goes through
    the facts-index, not through re-reading other articles)."""
    args = _args(article_file="article-03.md",
                 article_url=f"{rb.AIACT_SOURCE_URL_BASE}/article-03.md")
    text = rb._render_extraction_prompt(args, None)
    assert "article-03" in text
    for other in ("article-01.md", "article-02.md", "article-04.md",
                  "article-15.md"):
        assert other not in text, f"leaked other article: {other}"


def test_render_aiact_whole_corpus_unchanged_without_article():
    """Without a bound article the aiact render keeps the WHOLE-CORPUS
    template byte-for-byte (regression guard for the tick-2 path)."""
    args = _args()
    text = rb._render_extraction_prompt(args, None)
    assert "per-PARAGRAPH extraction pipeline" in text
    assert "article-01.md` .. `article-15.md" in text
    assert "THIS turn's scope" not in text
    assert "{{ARTICLE_FILE}}" not in text  # token absent from this template
    # second render is identical (no cross-call state)
    assert rb._render_extraction_prompt(args, None) == text


# ---------------------------------------------------------------------------
# per-article checkpoint poll
# ---------------------------------------------------------------------------

def test_poll_article_checkpoint_found():
    """The boundary is the content predicate: the manifest's
    ARTICLE-COMPLETE line for THIS article (not an mtime — the manifest
    accumulates and exists before this article's turn starts)."""
    with tempfile.TemporaryDirectory() as td:
        ckpt = Path(td) / "knowledge-checkpoints"
        ckpt.mkdir()
        (ckpt / rb.AIACT_MANIFEST_NAME).write_text(
            "ARTICLE-COMPLETE: article-01 2026-11-12T01:00:00Z 5 predicates\n"
            "ARTICLE-COMPLETE: article-02 2026-11-12T01:10:00Z 7 predicates\n",
            encoding="utf-8")
        paths = {"facts_index": Path(td) / "facts-index.md"}
        originals = {name: getattr(rb, name) for name in
                     ("_checkpoint_dir", "_bench_paths", "_sudo_read",
                      "_profile")}
        try:
            rb._checkpoint_dir = lambda args: ckpt
            rb._bench_paths = lambda args: paths
            rb._sudo_read = lambda p, timeout=60: (
                (ckpt / rb.AIACT_MANIFEST_NAME).read_text()
                if p == ckpt / rb.AIACT_MANIFEST_NAME else "x\n")
            rb._profile = lambda args: rb.OMEGA_PROFILE
            poll = rb._poll_article_checkpoint(
                _args(case="extract-a02", article_file="article-02.md"),
                "article-02", "2026-11-12T01:05:00Z",
                timeout_s=1.0, interval_s=0.001, _sleep=lambda s: None)
            assert poll["found"] is True
            assert "article-02" in poll["line"]
            # a DIFFERENT article's line is NOT this article's boundary
            poll1 = rb._poll_article_checkpoint(
                _args(case="extract-a03", article_file="article-03.md"),
                "article-03", "2026-11-12T01:05:00Z",
                timeout_s=0.05, interval_s=0.001, _sleep=lambda s: None)
            assert poll1["found"] is False
        finally:
            for name, value in originals.items():
                setattr(rb, name, value)


def test_poll_article_checkpoint_stall_reissue_then_boundary():
    """Stall semantics mirror the manifest poll: no forward signal for
    the stall window -> ONE delivery re-issue (rate-limited), keep
    polling; the re-issued turn's manifest line ends the wait."""
    state = {"reissued": False, "reissues": []}

    def fake_sudo_read(p, timeout=60):
        # the boundary line appears only AFTER the re-issue (the
        # re-issued turn writes it) — deterministic ordering: the stall
        # MUST fire first, or the poll never finds the line
        base = "ARTICLE-COMPLETE: article-01 2026-11-12T01:00:00Z 5 p\n"
        if not state["reissued"]:
            return base
        return base + ("ARTICLE-COMPLETE: article-02 2026-11-12T01:20:00Z"
                       " 7 p\n")

    def fake_reissue(args, session_key, stall_seconds, reason):
        state["reissues"].append((session_key, reason))
        state["reissued"] = True
        return True

    originals = {name: getattr(rb, name) for name in
                 ("_checkpoint_dir", "_bench_paths", "_sudo_read",
                  "_profile", "_maybe_reissue_delivery", "_delivery_exit",
                  "_recent_persist_signal", "_memory_volume")}
    try:
        rb._checkpoint_dir = lambda args: Path("/nonexistent")
        rb._bench_paths = lambda args: {"facts_index": Path("/nonexistent")}
        rb._sudo_read = fake_sudo_read
        rb._profile = lambda args: rb.OPENCLAW_PROFILE
        rb._maybe_reissue_delivery = fake_reissue
        rb._delivery_exit = lambda args, key: None  # turn still running
        rb._recent_persist_signal = lambda *a, **k: False
        rb._memory_volume = lambda args: "/fake/vol"
        poll = rb._poll_article_checkpoint(
            _args(case="extract-a02", article_file="article-02.md"),
            "article-02", "2026-11-12T01:05:00Z",
            timeout_s=10.0, interval_s=0.001,
            _sleep=lambda s: None, stall_minutes=0.001)
        assert poll["found"] is True, \
            "the boundary must be found after the re-issue"
        assert len(state["reissues"]) == 1, \
            "exactly one stall re-issue (rate-limited)"
        assert state["reissues"][0][0] == "extract-a02"
        assert "stall" in state["reissues"][0][1]
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)


def test_poll_article_checkpoint_timeout_not_found():
    """Timeout without the line: found=False, stall_aborted=False — the
    orchestrator records the article incomplete (no boundary invented)."""
    originals = {name: getattr(rb, name) for name in
                 ("_checkpoint_dir", "_bench_paths", "_sudo_read",
                  "_profile")}
    try:
        rb._checkpoint_dir = lambda args: Path("/nonexistent")
        rb._bench_paths = lambda args: {"facts_index": Path("/nonexistent")}
        rb._sudo_read = lambda p, timeout=60: ""
        rb._profile = lambda args: rb.OMEGA_PROFILE
        poll = rb._poll_article_checkpoint(
            _args(case="extract-a09", article_file="article-09.md"),
            "article-09", "2026-11-12T01:05:00Z",
            timeout_s=0.01, interval_s=0.001, _sleep=lambda s: None)
        assert poll["found"] is False and poll["line"] == ""
        assert poll["stall_aborted"] is False
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)


# ---------------------------------------------------------------------------
# article orchestrator
# ---------------------------------------------------------------------------

def test_run_article_extractions_subset_and_records():
    """The orchestrator loops the bound articles (the --articles subset
    filter accepts file names and stems), records per-article boundary /
    receipt / facts-index growth data, aggregates the shared summary,
    and restores the shared-extraction namespace (args.case /
    article_file) afterwards."""
    calls = {"setups": [], "polls": [], "copies": [], "inits": []}

    def fake_setup(args):
        calls["setups"].append((args.case, args.article_file,
                                args.article_url))
        return 0

    def fake_poll(args, stem, since, timeout_s=None, stall_minutes=0.0):
        calls["polls"].append(stem)
        return {"found": True, "line":
                f"ARTICLE-COMPLETE: {stem} 2026-11-12T01:00:00Z 4 predicates",
                "elapsed_s": 11, "timeout_s": timeout_s or 0,
                "poll_interval_s": 30.0, "since_iso": since,
                "stall_aborted": False}

    originals = {name: getattr(rb, name) for name in
                 ("RESULTS_DIR", "_bench_paths", "_sudo_write", "_sudo_read",
                  "_sweep_stale_manifests", "setup_extraction_phase",
                  "_poll_article_checkpoint", "_snapshot_phase1_logs",
                  "_copy_window_artifacts", "_census_persist_receipts",
                  "_load_json", "_write_json", "_profile",
                  "_memory_volume")}
    try:
        with tempfile.TemporaryDirectory() as td:
            rb.RESULTS_DIR = Path(td)
            rb._bench_paths = lambda args: {
                "answers": Path(td) / "answers.md",
                "facts_index": Path(td) / "facts-index.md"}

            def fake_write(p, s, timeout=60):
                calls["inits"].append(Path(p).name)
                return True
            rb._sudo_write = fake_write
            rb._sudo_read = lambda p, timeout=60: "h\nx\ny\n"  # 3 lines
            rb._sweep_stale_manifests = lambda args: ["dead-run.md"]
            rb.setup_extraction_phase = fake_setup
            rb._poll_article_checkpoint = fake_poll
            rb._snapshot_phase1_logs = (
                lambda args, since: {"path": "snap", "bytes": 1})
            rb._copy_window_artifacts = (
                lambda args, case: calls["copies"].append(case))
            rb._census_persist_receipts = (
                lambda since, until, profile=None, memory_volume=None,
                extra_logs="": {"count": 3})
            rb._load_json = lambda path: {"restarted_at": "2026-11-12T01:00:00Z"}
            rb._write_json = lambda path, data: None
            args = _args(articles="article-02,article-03.md")
            summary, harness_error = rb._run_article_extractions(args)
            assert harness_error is False
            # subset filter: 2 articles, ascending
            assert calls["polls"] == ["article-02", "article-03"]
            # per-article setup bound file + URL + pseudo-case session
            assert calls["setups"][0] == (
                "extract-a02", "article-02.md",
                f"{rb.AIACT_SOURCE_URL_BASE}/article-02.md")
            assert calls["setups"][1][0] == "extract-a03"
            # namespace restored
            assert args.case == rb.EXTRACT_PSEUDO_CASE
            assert args.article_file == "" and args.article_url == ""
            # per-article records + aggregates
            assert summary["per_article"] is True
            assert summary["articles_completed"] == 2
            assert summary["articles_total"] == 2
            assert summary["manifest_found"] is True
            assert summary["persist_receipts"] == 6
            assert summary["articles"]["article-02"]["persist_receipts"] == 3
            assert summary["articles"]["article-03"]["boundary_line"].startswith(
                "ARTICLE-COMPLETE: article-03")
            # facts-index growth accounting (3 -> 3 lines: static stub)
            assert summary["articles"]["article-02"][
                "facts_index_lines_before"] == 3
            # window copies per article
            assert calls["copies"] == ["extract-a02", "extract-a03"]
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)


def test_run_article_extractions_all_fifteen_by_default():
    """Default (no --articles): all 15 corpus articles, ascending."""
    calls = {"polls": []}
    originals = {name: getattr(rb, name) for name in
                 ("RESULTS_DIR", "_bench_paths", "_sudo_write", "_sudo_read",
                  "_sweep_stale_manifests", "setup_extraction_phase",
                  "_poll_article_checkpoint", "_snapshot_phase1_logs",
                  "_copy_window_artifacts", "_census_persist_receipts",
                  "_load_json", "_write_json", "_profile",
                  "_memory_volume")}
    try:
        with tempfile.TemporaryDirectory() as td:
            rb.RESULTS_DIR = Path(td)
            rb._bench_paths = lambda args: {
                "answers": Path(td) / "answers.md",
                "facts_index": Path(td) / "facts-index.md"}
            rb._sudo_write = lambda p, s, timeout=60: True
            rb._sudo_read = lambda p, timeout=60: ""
            rb._sweep_stale_manifests = lambda args: []
            rb.setup_extraction_phase = lambda args: 0
            rb._poll_article_checkpoint = (
                lambda args, stem, since, timeout_s=None, stall_minutes=0.0:
                (calls["polls"].append(stem)
                 or {"found": False, "line": "", "elapsed_s": 1,
                     "timeout_s": 0, "poll_interval_s": 30.0,
                     "since_iso": since, "stall_aborted": False}))
            rb._snapshot_phase1_logs = lambda args, since: {"path": "s"}
            rb._copy_window_artifacts = lambda args, case: None
            rb._census_persist_receipts = (
                lambda *a, **k: {"count": 0})
            rb._load_json = lambda path: {"restarted_at": "2026-11-12T01:00:00Z"}
            rb._write_json = lambda path, data: None
            summary, harness_error = rb._run_article_extractions(_args())
            assert harness_error is False
            assert len(calls["polls"]) == 15
            assert calls["polls"][0] == "article-01"
            assert calls["polls"][-1] == "article-15"
            # incomplete articles: recorded, aggregate gate False — but
            # the loop moved on (all 15 polls happened)
            assert summary["articles_completed"] == 0
            assert summary["manifest_found"] is False
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)


def test_run_article_extractions_setup_error_stops_loop():
    """A setup failure is a harness error and STOPS the loop (no blind
    delivery into a broken gateway); earlier articles keep their
    records."""
    setups = {"n": 0, "polls": []}

    def fake_setup(args):
        setups["n"] += 1
        if setups["n"] >= 2:
            return rb.GATE_ERROR
        return 0

    originals = {name: getattr(rb, name) for name in
                 ("RESULTS_DIR", "_bench_paths", "_sudo_write", "_sudo_read",
                  "_sweep_stale_manifests", "setup_extraction_phase",
                  "_poll_article_checkpoint", "_snapshot_phase1_logs",
                  "_copy_window_artifacts", "_census_persist_receipts",
                  "_load_json", "_write_json", "_profile",
                  "_memory_volume")}
    try:
        with tempfile.TemporaryDirectory() as td:
            rb.RESULTS_DIR = Path(td)
            rb._bench_paths = lambda args: {
                "answers": Path(td) / "answers.md",
                "facts_index": Path(td) / "facts-index.md"}
            rb._sudo_write = lambda p, s, timeout=60: True
            rb._sudo_read = lambda p, timeout=60: ""
            rb._sweep_stale_manifests = lambda args: []
            rb.setup_extraction_phase = fake_setup
            rb._poll_article_checkpoint = (
                lambda args, stem, since, timeout_s=None, stall_minutes=0.0:
                (setups["polls"].append(stem)
                 or {"found": True, "line": "x", "elapsed_s": 1,
                     "timeout_s": 0, "poll_interval_s": 30.0,
                     "since_iso": since, "stall_aborted": False}))
            rb._snapshot_phase1_logs = lambda args, since: {"path": "s"}
            rb._copy_window_artifacts = lambda args, case: None
            rb._census_persist_receipts = lambda *a, **k: {"count": 1}
            rb._load_json = lambda path: {"restarted_at": "2026-11-12T01:00:00Z"}
            rb._write_json = lambda path, data: None
            summary, harness_error = rb._run_article_extractions(
                _args(articles="article-01,article-02,article-03"))
            assert harness_error is True
            assert setups["polls"] == ["article-01"]  # loop stopped at 2nd
            assert summary["articles"]["article-02"]["verdict"] == "ERROR"
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)


# ---------------------------------------------------------------------------
# setup_case per-article gating (never first: no facts-index re-init,
# no mid-run manifest sweep)
# ---------------------------------------------------------------------------

def _setup_case_stub_env(td):
    """Shared stub environment for driving setup_case without IO."""
    vol = Path(td) / "vol"
    paths = {
        "vol": vol, "bench": vol / "bench",
        "answers": vol / "bench/answers.md",
        "facts_index": vol / "bench/facts-index.md",
        "urls": vol / "bench/urls.md",
        "prompt": vol / "prompt.txt", "state": vol / "prompt.txt",
        "history": vol / "history.metta",
    }
    writes = {"files": [], "dirs": []}
    env = {
        "paths": paths, "writes": writes, "sweeps": [], "renders": [],
        "restarts": [], "turns": []}

    def fake_sudo_write(p, s, timeout=60):
        writes["files"].append(Path(p).name)
        return True

    env["stubs"] = {
        "RESULTS_DIR": Path(td) / "results",
        "_bench_paths": lambda args: paths,
        "_prepare_benchmark_dir": lambda args: None,
        "_sudo_run": lambda cmd, timeout=None, **kw: SimpleNamespace(
            returncode=0, stdout="", stderr=""),
        "_sudo_write": fake_sudo_write,
        "_sweep_stale_manifests": (
            lambda args: env["sweeps"].append(args.run_id) or ["old.md"]),
        "_render_extraction_prompt": (
            lambda args, case: env["renders"].append(args.case) or "EXT"),
        "_agent_restart": lambda profile=None: env["restarts"].append(1)
        or True,
        "_start_agent_turn": (
            lambda args, key: env["turns"].append(key) or True),
        "_write_json": lambda path, data: None,
        "_load_json": lambda path: None,
    }
    return env


def test_setup_case_aiact_per_article_never_first():
    """Per-article setup is NEVER `first`: no answers/facts-index re-init
    (the orchestrator initializes once — a mid-run re-init would wipe
    the cross-article carry-over) and NO stale-manifest sweep (the
    manifest accumulates the 15 ARTICLE-COMPLETE lines). The
    whole-corpus extraction keeps today's behavior (sweep + fresh
    facts-index)."""
    with tempfile.TemporaryDirectory() as td:
        env = _setup_case_stub_env(td)
        originals = {name: getattr(rb, name)
                     for name in env["stubs"]}
        try:
            for name, stub in env["stubs"].items():
                setattr(rb, name, stub)
            # per-article setup (article 7 of the run)
            args = _args(case="extract-a07", article_file="article-07.md",
                         article_url="http://x/article-07.md")
            rc = rb.setup_case(args, phase="extraction")
            assert rc == 0
            assert env["sweeps"] == [], "per-article setup must NOT sweep"
            assert "facts-index.md" not in env["writes"]["files"], \
                "per-article setup must NOT re-init the facts-index"
            assert "answers.md" not in env["writes"]["files"]
            # the per-article turn was delivered with its own session key
            assert env["turns"] == ["extract-a07"]
            # contrast: the whole-corpus extraction setup (no bound
            # article) keeps today's behavior — sweep + fresh record
            env["sweeps"].clear()
            env["writes"]["files"].clear()
            env["renders"].clear()
            args2 = _args(case=rb.EXTRACT_PSEUDO_CASE)
            rc2 = rb.setup_case(args2, phase="extraction")
            assert rc2 == 0
            assert env["sweeps"] == ["t-run"], \
                "whole-corpus extraction keeps the stale-manifest sweep"
            assert "facts-index.md" in env["writes"]["files"]
            assert "answers.md" in env["writes"]["files"]
            # the per-article render reached the renderer (scoped prompt)
            assert env["renders"] and env["renders"][0] in (
                "extract-a07", rb.EXTRACT_PSEUDO_CASE)
        finally:
            for name, value in originals.items():
                setattr(rb, name, value)


# ---------------------------------------------------------------------------
# full_shared_kb wiring + per-article completion gate verdict
# ---------------------------------------------------------------------------

def _run_full_extraction_only(shared, harness_error=False):
    """Drive full_shared_kb in --extraction-only + aiact mode with the
    article orchestrator stubbed; returns (rc, grade.json)."""
    originals = {name: getattr(rb, name) for name in
                 ("RESULTS_DIR", "preflight", "cleanup_das",
                  "_run_article_extractions", "report", "teardown",
                  "_write_json", "_facts_mod")}
    try:
        with tempfile.TemporaryDirectory() as td:
            rb.RESULTS_DIR = Path(td)
            rb.preflight = lambda args: 0
            rb.cleanup_das = lambda args: 0
            rb._run_article_extractions = (
                lambda args: (shared, harness_error))
            rb.report = lambda args: None
            rb.teardown = lambda args: 0

            def write_json(path, data):
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")
            rb._write_json = write_json
            import facts as facts_mod
            rb._facts_mod = lambda: facts_mod
            args = _args(cases="", skip_report=True, force=False,
                         cleanup_first=False, stall_minutes=15,
                         trim_history=True, phase_timeout_minutes=30)
            rc = rb.full_shared_kb(args)
            grade = json.loads((Path(td) / "t-run" / "grade.json")
                               .read_text(encoding="utf-8"))
            return rc, grade
    finally:
        for name, value in originals.items():
            setattr(rb, name, value)


def test_full_extraction_only_aiact_gate_verdicts():
    """The per-article branch replaces the single shared turn, the
    per-article summary lands in grade.json, and the completion gate
    FAILS when any article is incomplete (a knowingly-partial KB is not
    a PASS) while all-15 COMPLETE passes."""
    complete = {"per_article": True,
                "articles": {f"article-{n:02d}": {"manifest_found": True}
                             for n in range(1, 16)},
                "articles_completed": 15, "articles_total": 15,
                "manifest_found": True, "persist_receipts": 150}
    rc, grade = _run_full_extraction_only(dict(complete))
    assert rc == rb.GATE_PASS
    assert grade["mode"] == "extraction-only"
    assert grade["shared_extraction"]["per_article"] is True
    assert grade["shared_extraction"]["articles_completed"] == 15
    assert grade["gate_verdict"] == "PASS"

    partial = dict(complete, articles_completed=14,
                   manifest_found=False)
    partial["articles"]["article-15"]["manifest_found"] = False
    rc2, grade2 = _run_full_extraction_only(partial)
    assert rc2 == rb.GATE_FAIL
    assert grade2["gate_verdict"] == "FAIL"
    assert grade2["shared_extraction"]["articles_completed"] == 14
