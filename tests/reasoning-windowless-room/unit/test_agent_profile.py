#!/usr/bin/env python3
"""OpenClaw-SUT adapter tests: the agent-profile seam (R-A1..R-A6, R-T1/R-T3).

Spec: specs/openclaw-sut-adapter/spec.md — the harness parameterizes the
agent under test through an explicit ``--agent-profile`` seam:

- omega (default) MUST resolve to today's exact constants (byte-for-byte
  behavior — the control arm of the comparison);
- openclaw resolves the SUT gateway container / workspace volume /
  benchmark-relative prompt paths / prompt.txt state file /
  openclaw-sut.service restart, delivers the case prompt via
  ``docker exec ... openclaw agent --message-file ... --session-id
  wr-<run_id>-<case_id> --no-color`` (R-A2), and unions the persist-receipt
  census with the receipts sidecar (R-A3);
- preflight asserts the Omega agent container is ABSENT/STOPPED for the
  openclaw profile (R-A5) and the openclaw-only check set;
- dry-run prints the profile-resolved plan (including the exact agent-turn
  command) without executing anything (R-A6/R-T3 — no docker needed).

All tests are pure logic (monkeypatched IO — no docker, no sudo, no network).
"""
import io
import json
import os
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import run_benchmark as rb


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class _Patch:
    """Context manager swapping run_benchmark module attributes."""

    def __init__(self, **overrides):
        self.overrides = overrides
        self.saved = {}

    def __enter__(self):
        for name, value in self.overrides.items():
            self.saved[name] = getattr(rb, name)
            setattr(rb, name, value)
        return rb

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(rb, name, value)
        return False


def _args(**kw):
    """An args namespace with the common CLI fields (profile-routable)."""
    base = {
        "run_id": "t-run", "case": "original", "dry_run": False,
        "agent_profile": "omega", "memory_volume": "/fake/vol",
        "timeout_minutes": 75, "trim_history": True, "force": False,
        "stall_minutes": 0, "phase_timeout_minutes": 0,
        "write_bridge": "http://172.20.0.5:8080",
        "read_proxy": "http://172.20.0.3:8080",
        "provenance_repo": "/home/ubuntu/omega-provenance",
    }
    base.update(kw)
    missing = object()
    return SimpleNamespace(**{k: v for k, v in base.items()
                              if v is not missing})


def _cleanup_results(run_id):
    rd = rb.RESULTS_DIR / run_id
    if rd.is_dir():
        import shutil
        shutil.rmtree(rd, ignore_errors=True)


# ---------------------------------------------------------------------------
# R-A1: profile resolution — omega is today's exact constants
# ---------------------------------------------------------------------------

def test_omega_profile_is_todays_exact_constants():
    p = rb.OMEGA_PROFILE
    assert p.name == "omega"
    assert p.container_agent == rb.CONTAINER_AGENT == "omega-curiosity"
    assert p.memory_volume_default == rb.DEFAULT_MEMORY_VOLUME
    assert p.bench_prompt_rel == rb.BENCH_PROMPT_REL \
        == "repos/Omega/memory/benchmark"
    assert p.state_file == "omega_state.md"
    assert rb._restart_command(p) == [
        "sudo", "systemctl", "restart", "omega-curiosity.service"]
    assert p.prompt_delivery == "restart_only"
    assert p.receipts_source == "docker_logs"
    assert p.delivers_agent_turn is False
    assert p.uses_receipts_sidecar is False
    # the three derived prompt-relative paths are the frozen v11 constants
    assert p.answers_prompt_rel == rb.ANSWERS_PROMPT_REL
    assert p.facts_index_prompt_rel == rb.FACTS_INDEX_PROMPT_REL
    assert p.urls_prompt_rel == rb.URLS_PROMPT_REL


def test_openclaw_profile_resolves_per_spec():
    p = rb.OPENCLAW_PROFILE
    assert p.name == "openclaw"
    assert p.container_agent == "openclaw-sut-gateway"
    assert p.memory_volume_default == (
        "/var/lib/docker/volumes/openclaw-sut-workspace/_data")
    assert p.bench_prompt_rel == "benchmark"
    assert p.answers_prompt_rel == "benchmark/answers.md"
    assert p.facts_index_prompt_rel == "benchmark/facts-index.md"
    assert p.urls_prompt_rel == "benchmark/urls.txt"
    assert p.state_file == "prompt.txt"
    assert rb._restart_command(p) == [
        "sudo", "systemctl", "restart", "openclaw-sut.service"]
    assert p.prompt_delivery == "file_plus_agent_turn"
    assert p.receipts_source == "docker_logs_and_receipts_file"
    assert p.delivers_agent_turn is True
    assert p.uses_receipts_sidecar is True
    assert p.prompt_abs_in_container == "/var/openclaw/workspace/prompt.txt"


def test_profile_resolution_default_and_explicit():
    assert rb._profile(_args()).name == "omega"
    assert rb._profile(_args(agent_profile="openclaw")).name == "openclaw"
    # a namespace without the attribute (legacy callers/tests) = omega
    assert rb._profile(SimpleNamespace()).name == "omega"


def test_parser_wires_agent_profile():
    args = rb.build_parser().parse_args(["full", "--run-id", "t"])
    assert args.agent_profile == "omega"
    args = rb.build_parser().parse_args(
        ["full", "--run-id", "t", "--agent-profile", "openclaw"])
    assert args.agent_profile == "openclaw"
    # every subcommand carries the seam (add_common)
    args = rb.build_parser().parse_args(
        ["preflight", "--agent-profile", "openclaw"])
    assert args.agent_profile == "openclaw"


def test_memory_volume_resolves_per_profile():
    # explicit --memory-volume always wins
    assert rb._memory_volume(_args(memory_volume="/x")) == "/x"
    # absent: the profile default
    args = SimpleNamespace(agent_profile="omega")
    assert rb._memory_volume(args) == rb.DEFAULT_MEMORY_VOLUME
    args = SimpleNamespace(agent_profile="openclaw")
    assert rb._memory_volume(args) == (
        "/var/lib/docker/volumes/openclaw-sut-workspace/_data")
    # empty-string (the parser sentinel) resolves the same way
    args = rb.build_parser().parse_args(
        ["full", "--run-id", "t", "--agent-profile", "openclaw"])
    assert args.memory_volume == ""
    assert rb._memory_volume(args) == (
        "/var/lib/docker/volumes/openclaw-sut-workspace/_data")


def test_bench_paths_per_profile():
    om = rb._bench_paths(_args())
    assert om["state"] == Path("/fake/vol/omega_state.md")
    assert om["prompt"] == Path("/fake/vol/prompt.txt")
    assert om["state"] != om["prompt"]
    assert om["receipts_sidecar"] is None
    oc = rb._bench_paths(_args(agent_profile="openclaw"))
    assert oc["state"] == oc["prompt"] == Path("/fake/vol/prompt.txt")
    assert oc["history"] == Path("/fake/vol/history.metta")
    assert oc["receipts_sidecar"] == Path(
        "/fake/vol/benchmark/persist-receipts.log")


def test_rendered_prompt_paths_per_profile():
    case = {"id": "original", "question": "q"}
    om = rb._render_case_prompt(_args(), case)
    assert "repos/Omega/memory/benchmark/answers.md" in om
    assert "repos/Omega/memory/benchmark/facts-index.md" in om
    assert "repos/Omega/memory/benchmark/urls.txt" in om
    # the frozen template's hard-coded background + checkpoint references
    # resolve against the OMEGA volume paths (identity mapping)
    assert "repos/Omega/memory/benchmark/background/" in om
    assert "/PeTTa/repos/Omega/memory/knowledge-checkpoints/" in om
    oc = rb._render_case_prompt(_args(agent_profile="openclaw"), case)
    assert "benchmark/answers.md" in oc
    assert "benchmark/facts-index.md" in oc
    assert "benchmark/urls.txt" in oc
    assert "repos/Omega/memory" not in oc
    assert "/PeTTa" not in oc
    # the hard-coded references remap onto the openclaw workspace
    assert "benchmark/background/" in oc
    assert "/var/openclaw/workspace/knowledge-checkpoints/" in oc
    # omega identity mapping: the rendered prompt is byte-for-byte today's
    assert rb._apply_profile_prompt_paths("x repos/Omega/memory/benchmark y "
                                          "/PeTTa/repos/Omega/memory z",
                                          rb.OMEGA_PROFILE) == \
        "x repos/Omega/memory/benchmark y /PeTTa/repos/Omega/memory z"


def test_agent_restart_profile_routing():
    """_agent_restart() zero-arg keeps the omega command (its historical
    test stubs depend on it); the profile routes the unit."""
    calls = []

    def fake_sudo(cmd, timeout=60.0):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with _Patch(_sudo_run=fake_sudo):
        assert rb._agent_restart() is True
        assert calls == [["systemctl", "restart", "omega-curiosity.service"]]
        assert rb._agent_restart(rb.OPENCLAW_PROFILE) is True
        assert calls[-1] == ["systemctl", "restart", "openclaw-sut.service"]


# ---------------------------------------------------------------------------
# R-A2: delivery command construction + re-issue machinery
# ---------------------------------------------------------------------------

def test_delivery_command_exact_argv():
    cmd = rb._delivery_command(_args(agent_profile="openclaw"), "false")
    assert cmd == [
        "docker", "exec", "openclaw-sut-gateway",
        "openclaw", "agent",
        "--message-file", "/var/openclaw/workspace/prompt.txt",
        "--session-id", "wr-t-run-false",
        "--no-color",
    ]


def test_delivery_command_session_id_format():
    cmd = rb._delivery_command(
        _args(agent_profile="openclaw", run_id="20261103-101530"),
        "unsolvable")
    assert cmd[cmd.index("--session-id") + 1] == "wr-20261103-101530-unsolvable"


def test_delivery_command_empty_for_omega():
    assert rb._delivery_command(_args(), "original") == []


class _FakeProc:
    def __init__(self, rc=None):
        self._rc = rc
        self.killed = False

    def poll(self):
        return self._rc

    def kill(self):
        self.killed = True


def test_reissue_kills_running_turn():
    key = ("t-run", "original")
    proc = _FakeProc(rc=None)  # hung turn, still running
    rb._DELIVERY_PROCS[key] = {"proc": proc, "argv": [], "issues": 1,
                               "last_reissue": 0.0}
    started = []

    def fake_start(args, case_id):
        started.append(case_id)
        rb._DELIVERY_PROCS[key] = {"proc": _FakeProc(rc=0), "argv": [],
                                   "issues": 2, "last_reissue": 0.0}
        return True

    try:
        with _Patch(_start_agent_turn=fake_start):
            assert rb._reissue_agent_turn(_args(agent_profile="openclaw"),
                                          "original") is True
        assert proc.killed is True
        assert started == ["original"]
    finally:
        rb._DELIVERY_PROCS.pop(key, None)


def test_maybe_reissue_rate_limited_by_stall_window():
    key = ("t-run", "original")
    rb._DELIVERY_PROCS[key] = {
        "proc": _FakeProc(rc=1), "argv": [], "issues": 1,
        "last_reissue": time.time(),  # re-issued moments ago
    }
    reissues = []

    def fake_start(args, case_id):
        reissues.append(case_id)
        return True

    try:
        with _Patch(_start_agent_turn=fake_start):
            out = rb._maybe_reissue_delivery(
                _args(agent_profile="openclaw"), "original", 900.0, "test")
        assert out is False
        assert reissues == []  # this stall window already re-issued
    finally:
        rb._DELIVERY_PROCS.pop(key, None)


def test_maybe_reissue_fires_after_stall_window():
    key = ("t-run", "original")
    rb._DELIVERY_PROCS[key] = {
        "proc": _FakeProc(rc=1), "argv": [], "issues": 1,
        "last_reissue": time.time() - 1000.0,  # a full window ago
    }
    reissues = []

    def fake_start(args, case_id):
        reissues.append(case_id)
        return True

    try:
        with _Patch(_start_agent_turn=fake_start):
            out = rb._maybe_reissue_delivery(
                _args(agent_profile="openclaw"), "original", 900.0, "test")
        assert out is True
        assert reissues == ["original"]
        assert rb._DELIVERY_PROCS[key]["last_reissue"] > 0
    finally:
        rb._DELIVERY_PROCS.pop(key, None)


def test_maybe_reissue_noop_for_omega():
    assert rb._maybe_reissue_delivery(_args(), "original", 900.0, "test") \
        is False
    assert rb._maybe_reissue_delivery(
        _args(agent_profile="openclaw", dry_run=True), "original", 900.0,
        "test") is False


# ---------------------------------------------------------------------------
# R-A3: receipts sidecar census — union + dedup + window (fixtures)
# ---------------------------------------------------------------------------

H1 = "a" * 32
H2 = "b" * 32
H3 = "c" * 32
H4 = "d" * 32

DOCKER_WINDOW_LOGS = "\n".join([
    # emission lane: real receipt (docker --timestamps nano prefix)
    f"2026-11-03T10:00:00.123456789Z COMMAND_RETURN: ((metta \"(add-atom &persistent (A) \\\"u\\\" (stv 0.9 0.8))\") \"SUCCESS, RETURN: BRIDGE-PERSIST-OK: verified=1 top={H1}\")",
    # interleaved noise: the prompt-echo lane must be EXCLUDED
    f"2026-11-03T10:01:00.000000000Z LLMRequest[system prompt ... BRIDGE-PERSIST-OK: verified=2 top={H2} ...]",
    # a second real receipt only in docker logs
    f"2026-11-03T10:10:00.500000000Z COMMAND_RETURN: ((metta \"(add-atom &persistent (B) \\\"u\\\")\") \"SUCCESS, RETURN: BRIDGE-PERSIST-OK: verified=1 top={H3}\")",
    # an unrelated line
    "2026-11-03T10:11:00Z gateway: turn complete",
])

SIDECAR_FIXTURE = "\n".join([
    # the SAME receipt as the docker H1 line, same second → deduped
    f"2026-11-03T10:00:00Z BRIDGE-PERSIST-OK: verified=1 top={H1}",
    # a sidecar-only receipt INSIDE the window → union adds it
    f"2026-11-03T10:05:00Z BRIDGE-PERSIST-OK: verified=1 top={H2}",
    # a sidecar-only receipt BEFORE the window → excluded
    f"2026-11-03T09:00:00Z BRIDGE-PERSIST-OK: verified=1 top={H4}",
    # a sidecar-only receipt AFTER the window → excluded
    f"2026-11-03T11:00:00Z BRIDGE-PERSIST-OK: verified=1 top={H4}",
    # malformed lines → ignored, never crash
    "BRIDGE-PERSIST-OK: verified=1 top=" + H4 + " (no timestamp prefix)",
    "2026-11-03T10:06:00Z not-a-receipt-line",
    "",
])

SINCE = "2026-11-03T09:55:00Z"
UNTIL = "2026-11-03T10:30:00Z"


def test_union_receipt_census_union_dedup_window():
    docker_matched = [
        f"2026-11-03T10:00:00.123456789Z COMMAND_RETURN: ... BRIDGE-PERSIST-OK: verified=1 top={H1})",
        f"2026-11-03T10:10:00.500000000Z COMMAND_RETURN: ... BRIDGE-PERSIST-OK: verified=1 top={H3})",
    ]
    out = rb._union_receipt_census(docker_matched, SIDECAR_FIXTURE,
                                   SINCE, UNTIL)
    # H1 appears in BOTH sources at the same second → counted ONCE
    assert sum(1 for ln in out if f"top={H1}" in ln) == 1
    # H2 (sidecar-only, in window) is unioned in
    assert any(f"2026-11-03T10:05:00Z BRIDGE-PERSIST-OK: verified=1 top={H2}"
               == ln for ln in out)
    # H3 (docker-only) survives
    assert any(f"top={H3}" in ln for ln in out)
    # out-of-window sidecar receipts (H4) are excluded
    assert not any(f"top={H4}" in ln for ln in out)
    # count: docker H1 + docker H3 + sidecar H2
    assert len(out) == 3, out


def test_union_receipt_census_dedup_identical_pairs():
    sidecar = (f"2026-11-03T10:05:00Z BRIDGE-PERSIST-OK: verified=1 top={H2}\n"
               f"2026-11-03T10:05:00Z BRIDGE-PERSIST-OK: verified=1 top={H2}\n")
    out = rb._union_receipt_census([], sidecar, SINCE, UNTIL)
    assert len(out) == 1  # identical (timestamp, handle) pair deduped


def test_union_receipt_census_empty_sidecar_is_docker_only():
    docker_matched = [
        f"2026-11-03T10:00:00Z BRIDGE-PERSIST-OK: verified=1 top={H1}"]
    out = rb._union_receipt_census(docker_matched, "", SINCE, UNTIL)
    assert out == docker_matched


def test_census_persist_receipts_openclaw_unions_sidecar():
    """The full census (docker fetch + sidecar union) through the profile."""
    served = {}

    def fake_logs(container, since, until):
        served["container"] = container
        return DOCKER_WINDOW_LOGS

    def fake_sudo_read(path, timeout=60.0):
        if str(path).endswith("benchmark/persist-receipts.log"):
            return SIDECAR_FIXTURE
        return None

    with _Patch(_docker_logs_since=fake_logs, _sudo_read=fake_sudo_read):
        out = rb._census_persist_receipts(
            SINCE, UNTIL, profile=rb.OPENCLAW_PROFILE,
            memory_volume="/fake/vol")
    assert served["container"] == "openclaw-sut-gateway"
    # H1 (both sources, same second) once; H3 docker-only; H2 sidecar-only
    assert out["count"] == 3, out["matched"]
    assert out["sidecar"]["source"] == "benchmark/persist-receipts.log"
    assert out["sidecar"]["docker_matched"] == 2
    assert out["sidecar"]["union_count"] == 3


def test_census_persist_receipts_omega_unchanged_no_sidecar():
    """omega: no sidecar key, docker-only census, exact historical shape."""
    def fake_logs(container, since, until):
        assert container == rb.CONTAINER_AGENT
        return DOCKER_WINDOW_LOGS

    with _Patch(_docker_logs_since=fake_logs):
        out = rb._census_persist_receipts(SINCE, UNTIL)
    assert out["count"] == 2  # H1 + H3; the LLMRequest echo (H2) excluded
    assert "sidecar" not in out
    assert all("LLMRequest[" not in ln for ln in out["matched"])
    assert out["window"] == [SINCE, UNTIL]


def test_census_persist_receipts_sidecar_unreadable_is_docker_only():
    """A missing/unreadable sidecar degrades to the docker-only census
    (docker errors are not gate evidence; neither are sidecar ones)."""
    with _Patch(_docker_logs_since=lambda c, s, u: DOCKER_WINDOW_LOGS,
                _sudo_read=lambda path, timeout=60.0: None):
        out = rb._census_persist_receipts(
            SINCE, UNTIL, profile=rb.OPENCLAW_PROFILE,
            memory_volume="/fake/vol")
    assert out["count"] == 2  # H1 + H3 from docker logs only
    assert out["sidecar"]["union_count"] == 2


def test_docker_log_timestamp_parsing():
    ts = rb._docker_log_timestamp(
        f"2026-11-03T10:00:00.123456789Z BRIDGE-PERSIST-OK: verified=1 top={H1}")
    assert ts is not None and ts.year == 2026
    assert rb._docker_log_timestamp("no prefix here") is None
    assert rb._docker_log_timestamp("") is None
    assert rb._parse_iso_utc("2026-11-03T10:00:00Z") is not None
    assert rb._parse_iso_utc("not-a-date") is None


# ---------------------------------------------------------------------------
# R-A5: preflight (openclaw) — command construction incl. Omega-stopped
# ---------------------------------------------------------------------------

def _openclaw_preflight(omega_ps_stdout="", extra_run=None):
    """Run the openclaw-profile preflight against stubbed subprocess output;
    return (rc, checks, commands)."""
    commands = []
    checks_out = {}

    def fake_run(cmd, timeout=30.0, **kw):
        commands.append(list(cmd))
        out = SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["docker", "ps"]:
            out.stdout = omega_ps_stdout
        elif cmd[:3] == ["docker", "network", "inspect"]:
            out.stdout = "openclaw-sut-gateway "
        if extra_run is not None:
            out = extra_run(cmd, out)
        return out

    def fake_sudo_run(cmd, timeout=60.0, **kw):
        cmd = [str(c) for c in cmd]
        # `test -f <backup>` must NOT find a pre-existing backup
        if cmd[:2] == ["test", "-f"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_http_post(url, body, timeout=30.0):
        return {"count": 4}

    def fake_write_json(path, data):
        checks_out["data"] = data

    def fake_judge_getter(args):
        return lambda case, ans: (True, "")

    with _Patch(_run=fake_run, _sudo_run=fake_sudo_run,
                _sudo_read=lambda path, timeout=60.0: "standby prompt",
                _http_post=fake_http_post,
                _container_ip=lambda c, a=None: "172.20.0.9",
                _write_bridge_smoke_v4=lambda args: ("ok", "ok"),
                _ledger_repo_format=lambda args: "ok",
                _get_judge=fake_judge_getter,
                _write_json=fake_write_json,
                _resolve_endpoints=lambda args: None):
        rc = rb.preflight(_args(agent_profile="openclaw", dry_run=False))
    return rc, checks_out.get("data", {}), commands


def test_openclaw_preflight_asserts_omega_stopped():
    rc, data, commands = _openclaw_preflight(omega_ps_stdout="")
    assert rc == 0
    # the assert-Omega-stopped check: docker ps filter for omega-curiosity
    ps_cmd = ["docker", "ps", "--filter", "name=omega-curiosity",
              "--format", "{{.Names}}"]
    assert ps_cmd in commands
    checks = data["checks"]
    assert checks["omega_agent_stopped"] == "ok"
    # the other R-A5 assertions
    assert checks["gateway_on_das_network"] == "ok"
    assert checks["workspace_volume"] == "ok"
    assert checks["benchmark_artifacts_creatable"] == "ok"
    assert checks["write_bridge_reachable_from_sut"] == "ok"
    assert checks["read_proxy_reachable_from_sut"] == "ok"
    assert checks["sut_skills_present"] == "ok"
    # the gateway container is the profile's, on the client network
    assert checks["container_openclaw-sut-gateway"] == "running"
    assert checks["agent_ip"] == "172.20.0.9"
    # omega-only checks are ABSENT for the openclaw profile
    for key in ("skill_description_upgraded", "das_write_grammar_v3",
                "metta_skill_upgraded", "metta_plugin_mounted",
                "das_extract_knowledge_plugin_mounted",
                "das_grounded_reasoning_skill_description",
                "chroma_memory_dir"):
        assert key not in checks, key


def test_openclaw_preflight_fails_when_omega_running():
    rc, data, commands = _openclaw_preflight(
        omega_ps_stdout="omega-curiosity\n")
    assert rc == 1
    assert data["checks"]["omega_agent_stopped"].startswith("RUNNING")
    assert data["all_ok"] is False


def test_openclaw_preflight_reachability_commands():
    rc, data, commands = _openclaw_preflight()
    # the SUT-side reachability probes exec python3 socket connects on the
    # discovered DAS container IPs
    probes = [c for c in commands if c[:3] == ["docker", "exec",
                                               "openclaw-sut-gateway"]]
    assert any("create_connection" in " ".join(c) and "172.20.0.9" in c
               for c in probes)
    # the five skills are probed by directory
    for skill in ("das-write", "das-retrieve", "metta",
                  "das-extract-knowledge", "das-grounded-reasoning"):
        assert ["docker", "exec", "openclaw-sut-gateway", "test", "-d",
                f"/var/openclaw/workspace/skills/{skill}"] in commands


def test_omega_preflight_dry_run_keys_unchanged():
    """R-A6 regression pin: the omega dry-run check set is byte-identical."""
    def boom(cmd, timeout=30.0, **kw):
        raise AssertionError(f"dry-run must not run docker: {cmd}")

    def fake_write_json(path, data):
        fake_write_json.data = data
    fake_write_json.data = {}

    with _Patch(_container_ip=lambda c, a=None: "",
                _write_json=fake_write_json,
                _resolve_endpoints=lambda args: None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rb.preflight(_args(dry_run=True))
    assert rc == 0
    checks = fake_write_json.data["checks"]
    assert fake_write_json.data["all_ok"] is True
    for name in ("write_bridge_smoke", "read_proxy_query",
                 "ledger_repo_format", "memory_volume",
                 "prompt_backup_fresh", "standby_prompt_clean",
                 "skill_description_upgraded", "das_write_grammar_v3",
                 "metta_skill_upgraded", "metta_plugin_mounted",
                 "das_extract_knowledge_plugin_mounted",
                 "das_extract_knowledge_skill_description",
                 "das_grounded_reasoning_plugin_mounted",
                 "das_grounded_reasoning_skill_description",
                 "canary_fetch_ai", "judge_smoke"):
        assert checks[name] == "dry-run", name
    # openclaw-only keys are ABSENT for omega
    for key in rb._OPENCLAW_PREFLIGHT_KEYS:
        assert key not in checks, key


# ---------------------------------------------------------------------------
# R-A6 / R-T3: dry-run prints the profile-resolved plan; no docker needed
# ---------------------------------------------------------------------------

def test_openclaw_setup_case_dry_run_prints_delivery_command():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = rb.setup_case(_args(agent_profile="openclaw", dry_run=True))
    assert rc == 0
    out = buf.getvalue()
    assert ("docker exec openclaw-sut-gateway openclaw agent "
            "--message-file /var/openclaw/workspace/prompt.txt "
            "--session-id wr-t-run-original --no-color") in out


def test_omega_setup_case_dry_run_prints_exactly_the_old_plan():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = rb.setup_case(_args(dry_run=True))
    assert rc == 0
    assert buf.getvalue() == (
        "[setup-case] [dry-run] case original: prepare benchmark dir, "
        "backup prompt/state/history (run start), snapshot history, "
        "install rendered case prompt, trim history to the per-case window "
        "marker, restart agent\n")


def test_openclaw_dry_run_needs_no_docker():
    """R-T3: the openclaw preflight/setup/agent/wait dry-run paths never
    invoke docker (a _run/_sudo stub that raises proves it)."""
    def boom_run(cmd, *a, **kw):
        raise AssertionError(f"dry-run must not run subprocess: {cmd}")

    def boom_sudo_run(cmd, *a, **kw):
        raise AssertionError(f"dry-run must not sudo: {cmd}")

    def boom_sudo_read(path, *a, **kw):
        raise AssertionError(f"dry-run must not read: {path}")

    def fake_write_json(path, data):
        pass

    def fake_load_json(path):
        return {"restarted_at": "2026-11-03T10:00:00Z"}

    with _Patch(_run=boom_run, _sudo_run=boom_sudo_run,
                _sudo_read=boom_sudo_read, _sudo_write=lambda *a: True,
                _write_json=fake_write_json, _load_json=fake_load_json,
                _container_ip=lambda c, a=None: "",
                _resolve_endpoints=lambda args: None):
        args = _args(agent_profile="openclaw", dry_run=True)
        assert rb.preflight(args) == 0
        assert rb.setup_case(args) == 0
        assert rb.setup_extraction_phase(args) == 0
        assert rb.agent_case(args) == 0
        assert rb.wait_manifest(args) == 0
        assert rb.snapshot_phase1_logs(args) == 0
        assert rb.teardown(args) == 0


# ---------------------------------------------------------------------------
# R-A4: history handling identical for both profiles
# ---------------------------------------------------------------------------

def test_history_paths_and_trim_identical_per_profile():
    """history.metta lives at the volume root for BOTH profiles; the trim
    marker/snapshot logic is profile-independent (only the volume differs)."""
    oc = rb._bench_paths(_args(agent_profile="openclaw",
                               memory_volume="/oc-vol"))
    assert oc["history"] == Path("/oc-vol/history.metta")
    marker = rb._trim_marker("t-run", "original")
    assert marker == rb._trim_marker("t-run", "original")  # same function


def test_openclaw_setup_case_flow_against_fake_volume():
    """The openclaw setup writes the prompt, keeps prompt.txt as the state
    (no clobber), restarts via the profile unit, and starts the delivery
    turn after the restart."""
    files = {
        "/oc-vol/prompt.txt": "STANDBY PROMPT",
        "/oc-vol/history.metta": '(("2026-11-03 10:00:00" ((query "old")))\n',
        "/oc-vol/benchmark/answers.md": "old",
        "/oc-vol/benchmark/facts-index.md": "old",
    }
    calls = []
    restarts = []
    deliveries = []

    class FakeVol:
        def read(self, path, timeout=60.0):
            return files.get(str(path))

        def write(self, path, content, timeout=60.0):
            files[str(path)] = content
            return True

        def run(self, cmd, timeout=60.0):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            out = SimpleNamespace(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["test", "-f"]:
                out.returncode = 0 if cmd[2] in files else 1
            elif cmd[:2] == ["test", "-d"]:
                out.returncode = 0
            elif cmd[0] == "cp":
                src, dst = cmd[1], cmd[2]
                if src not in files:
                    out.returncode = 1
                else:
                    files[dst] = files[src]
            return out

    def fake_restart(profile=None):
        restarts.append(profile.name if profile else "omega")
        return True

    def fake_start(args, case_id):
        deliveries.append(case_id)
        return True

    def fake_write_json(path, data):
        pass

    with _Patch(_sudo_read=FakeVol().read, _sudo_write=FakeVol().write,
                _sudo_run=FakeVol().run,
                _prepare_benchmark_dir=lambda args: None,
                _agent_restart=fake_restart,
                _start_agent_turn=fake_start,
                _write_json=fake_write_json,
                _sweep_stale_manifests=lambda args: []):
        rc = rb.setup_case(_args(agent_profile="openclaw",
                                 memory_volume="/oc-vol"))
    assert rc == 0
    # prompt.txt written with the rendered case prompt...
    assert "{{" not in files["/oc-vol/prompt.txt"]
    assert "benchmark/answers.md" in files["/oc-vol/prompt.txt"]
    # ...and NOT clobbered by a state write (prompt.txt IS the state)
    assert "BENCHMARK MODE ACTIVE" not in files["/oc-vol/prompt.txt"]
    # standby backup created (state == prompt → same backup file name)
    assert files["/oc-vol/prompt.txt.bak-pre-benchmark-t-run"] \
        == "STANDBY PROMPT"
    # history trimmed to the per-case marker (R-A4: identical logic)
    assert files["/oc-vol/history.metta"] == rb._trim_marker("t-run",
                                                             "original")
    # restart via the openclaw unit + delivery turn started after it
    assert restarts == ["openclaw"]
    assert deliveries == ["original"]
    # the openclaw per-case chown keeps agent-writable ownership
    assert any(c[0] == "chown" and "1000:1000" in c for c in calls)


def test_openclaw_teardown_restores_standby_prompt():
    files = {
        "/oc-vol/prompt.txt": "BENCHMARK MODE ACTIVE — residue",
        "/oc-vol/prompt.txt.bak-pre-benchmark-t-run": "STANDBY PROMPT",
        "/oc-vol/history.bak-pre-benchmark-t-run": '(("old day history"))\n',
        "/oc-vol/history.metta": rb._trim_marker("t-run", "original"),
    }
    restarts = []

    class FakeVol:
        def read(self, path, timeout=60.0):
            return files.get(str(path))

        def write(self, path, content, timeout=60.0):
            files[str(path)] = content
            return True

        def run(self, cmd, timeout=60.0):
            cmd = [str(c) for c in cmd]
            out = SimpleNamespace(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["test", "-f"]:
                out.returncode = 0 if cmd[2] in files else 1
            elif cmd[0] == "cp" and cmd[1] in files:
                files[cmd[2]] = files[cmd[1]]
            elif cmd[0] == "cp":
                out.returncode = 1
            elif cmd[0] == "rm":
                for a in cmd[1:]:
                    if not a.startswith("-"):
                        files.pop(a, None)
            elif cmd[:2] == ["sudo", "test"]:
                out.returncode = 0
            return out

    def fake_subprocess_run(cmd, *a, **kw):
        cmd = [str(c) for c in cmd]
        if cmd[:3] == ["sudo", "tee", "-a"]:
            files[cmd[3]] = files.get(cmd[3], "") + (kw.get("input") or "")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    import subprocess as subprocess_mod

    def fake_restart(profile=None):
        restarts.append(profile.name if profile else "omega")
        return True

    def fake_write_json(path, data):
        pass

    with _Patch(_sudo_read=FakeVol().read, _sudo_write=FakeVol().write,
                _sudo_run=FakeVol().run,
                _agent_restart=fake_restart,
                _write_json=fake_write_json):
        saved_run = rb.subprocess.run
        rb.subprocess.run = fake_subprocess_run
        try:
            rc = rb.teardown(_args(agent_profile="openclaw",
                                   memory_volume="/oc-vol",
                                   keep_snapshots=True))
        finally:
            rb.subprocess.run = saved_run
    assert rc == 0
    # standby prompt restored (the state restore = the same prompt backup)
    assert files["/oc-vol/prompt.txt"] == (
        "STANDBY PROMPT" + "\nbenchmark complete (t-run), "
        "returned to standby\n")
    # pre-run history restored from the backup
    assert files["/oc-vol/history.metta"] == '(("old day history"))\n'
    assert restarts == ["openclaw"]
