#!/usr/bin/env python3
"""Evaluate ONE MeTTa s-expression with the upstream-pinned runtime.

The OpenClaw-SUT "teach OpenClaw MeTTa" skill's runtime wrapper (spec
R-S3, amended by specs/openclaw-sut-adapter/spec-addendum-metta-runtime.md
item 2): each invocation writes a temporary .metta program that loads
the vendored NAL/PLN libraries (``lib_nal.metta`` + ``lib_pln.metta`` via
absolute-path ``!(import! &self "<abs>")`` lines) and evaluates ONE
s-expression, then runs the pinned SWI-Prolog + PeTTa interpreter as a
subprocess — the same runtime Omega uses (swipl:10.0.2 + PeTTa v1.0.4,
commit 7037f4c2ad378c52fc328004fe216d5118b674f0):

    swipl --stack_limit=8g -q -s src/main.pl -- <tmpfile>   (cwd=/opt/petta)

A NEW swipl process per invocation IS the fresh ephemeral atomspace:
nothing persists across calls, matching the Omega runtime.

Usage:
    metta_run.py '<s-expression>'

The leading ``!`` eval prefix is optional (omitted in the skill contract;
prepended mechanically). The wrapped invocation form
``(metta "(...)")`` is accepted and unwrapped mechanically, mapping the
skill call to this script.

Output:
- success: the evaluation result lines (the interpreter's trace noise is
  dropped — ``--> ... -->`` blocks, ``^^^^`` separators, ``:- findall(...)``
  goal echoes and the bare ``true`` results of the library imports are
  NOT result lines; what remains, e.g. ``((--> mammal animal) (stv 1.0
  0.447...))``, is); an empty result prints ``()``
- input-shape errors: ``syntax_error: <detail>`` (empty or oversized
  expression)
- any other failure: a ``metta_error: <detail>`` status line (missing
  vendored lib, swipl runtime unavailable, nonzero swipl exit, timeout)

R-S8: an episode line (``; <iso> metta <summary>`` + the verbatim call
and result) is appended to ``<workspace>/history.metta`` — best-effort.

Environment:
    OPENCLAW_SUT_METTA_LIB_DIR   vendored libs dir (default /opt/sut-metta)
    OPENCLAW_SUT_WORKSPACE       workspace root (default: cwd)
    OPENCLAW_SUT_SWIPL_BIN       swipl binary (default /usr/bin/swipl)
    OPENCLAW_SUT_PETTA_DIR       PeTTa checkout (default /opt/petta)

The module never raises; failures surface as printed status strings.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone

DEFAULT_LIB_DIR = "/opt/sut-metta"
DEFAULT_SWIPL_BIN = "/usr/bin/swipl"
DEFAULT_PETTA_DIR = "/opt/petta"
LIB_NAL = "lib_nal.metta"
LIB_PLN = "lib_pln.metta"
MAX_EXPR_CHARS = 4096
SWIPL_TIMEOUT_S = 120
MAIN_PL_REL = "src/main.pl"  # relative to PETTA_DIR (cwd) — main.pl loads its src/ siblings

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TRACE_HEADER_RE = re.compile(r"^-->.*-->$")


def _env_get(name: str, default: str = "") -> str:
    value = os.environ.get(name, "")
    return value if isinstance(value, str) else default


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _workspace_root() -> str:
    return _env_get("OPENCLAW_SUT_WORKSPACE", "") or os.getcwd()


def _append_history_episode(summary: str, call: str, result: str) -> None:
    """R-S8: append an episode line to history.metta at the workspace
    root. BEST-EFFORT: the ledger stays current but an append failure
    never fails the evaluation."""
    try:
        path = os.path.join(_workspace_root(), "history.metta")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"; {_now_iso()} metta {summary}\n")
            f.write(f"{call} => {result}\n")
    except OSError:
        pass


def _unwrap_metta_call(text: str) -> str:
    """Mechanically map the invocation form ``(metta "(...)")`` to the
    bare s-expression (the quoted payload is unescaped)."""
    stripped = text.strip()
    if not stripped.startswith("(metta "):
        return stripped
    rest = stripped[len("(metta "):].lstrip()
    if not rest.startswith('"'):
        return stripped
    # scan the quoted string with escape awareness
    i = 1
    n = len(rest)
    out: list[str] = []
    while i < n:
        ch = rest[i]
        if ch == "\\" and i + 1 < n:
            out.append(rest[i + 1])
            i += 2
            continue
        if ch == '"':
            break
        out.append(ch)
        i += 1
    return "".join(out).strip()


def _is_caret_rule(line: str) -> bool:
    return len(line) >= 3 and set(line) == {"^"}


def _filter_output(text: str) -> list[str]:
    """Drop the interpreter's TRACE noise, keep the result lines.

    Noise (verified against the pinned runtime's live output): the
    ``--> ... -->`` trace headers and everything up to their closing
    ``^^^^`` separator (function/clause/sexpr/runnable/goal-echo blocks,
    including the ``:- findall(...)`` goal echoes), stray ``^^^^`` rules,
    and the bare ``true`` lines that are the RESULTS OF THE LIBRARY
    IMPORTS (each ``!(import! ...)`` form yields ``true``; the eval's
    own result line follows them). Result lines may span multiple lines
    (one per interpreter result)."""
    kept: list[str] = []
    in_trace = False
    for line in _ANSI_RE.sub("", text).split("\n"):
        s = line.rstrip()
        if _TRACE_HEADER_RE.match(s):
            in_trace = True
            continue
        if in_trace:
            if _is_caret_rule(s.strip()):
                in_trace = False
            continue
        if _is_caret_rule(s.strip()):
            continue
        if s.lstrip().startswith(":-"):
            continue  # goal echo outside a trace block (defensive)
        if s == "true":
            continue  # import! results, not the evaluation result
        kept.append(s)
    while kept and not kept[-1]:
        kept.pop()
    return kept


def _build_program(expression: str, lib_dir: str) -> str:
    """The temp .metta program: the two absolute-path import! lines
    (NAL first, then PLN — spec order) followed by the eval-prefixed
    expression."""
    nal = os.path.join(os.path.abspath(lib_dir), LIB_NAL)
    pln = os.path.join(os.path.abspath(lib_dir), LIB_PLN)
    return (
        f'!(import! &self "{nal}")\n'
        f'!(import! &self "{pln}")\n'
        f"!{expression}\n"
    )


def _write_program_file(program: str) -> str:
    """Write the program to a workspace-local temp file
    (``<workspace>/.metta-tmp/``; falls back to the system tmp dir if the
    workspace is not writable — the smoke gate points the workspace at a
    scratch dir, the ledger stays untouched either way)."""
    path = ""
    try:
        tmp_dir = os.path.join(_workspace_root(), ".metta-tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, f"metta-{os.getpid()}-{_now_iso().replace(':', '')}.metta")
        with open(path, "w", encoding="utf-8") as f:
            f.write(program)
        return path
    except OSError:
        import tempfile

        if path and os.path.exists(path):
            return path
        fd, fallback = tempfile.mkstemp(suffix=".metta", prefix="metta-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(program)
        return fallback


def _run_swipl(program_file: str) -> tuple[int, str, str]:
    """Run the pinned interpreter; return (exit_code, stdout, stderr)."""
    swipl = _env_get("OPENCLAW_SUT_SWIPL_BIN", DEFAULT_SWIPL_BIN) or DEFAULT_SWIPL_BIN
    petta_dir = _env_get("OPENCLAW_SUT_PETTA_DIR", DEFAULT_PETTA_DIR) or DEFAULT_PETTA_DIR
    proc = subprocess.run(
        [swipl, "--stack_limit=8g", "-q", "-s", MAIN_PL_REL, "--", program_file],
        cwd=petta_dir,
        capture_output=True,
        text=True,
        timeout=SWIPL_TIMEOUT_S,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _error_excerpt(stderr: str, stdout: str) -> str:
    for stream in (stderr, stdout):
        lines = [l.rstrip() for l in _ANSI_RE.sub("", stream).split("\n") if l.strip()]
        if lines:
            return " | ".join(lines[-3:])[:400]
    return "no output"


def run_expression(expression: str) -> tuple[str, bool]:
    """Evaluate ONE s-expression; return (output_text, ok)."""
    expr = _unwrap_metta_call(expression)
    # tolerate one optional leading "!" eval prefix
    if expr.startswith("!"):
        expr = expr[1:].lstrip()
    if not expr:
        return "syntax_error: empty expression", False
    if len(expr) > MAX_EXPR_CHARS:
        return f"syntax_error: expression exceeds {MAX_EXPR_CHARS} characters", False

    lib_dir = _env_get("OPENCLAW_SUT_METTA_LIB_DIR", DEFAULT_LIB_DIR) or DEFAULT_LIB_DIR
    for lib in (LIB_NAL, LIB_PLN):
        # the pinned runtime does NOT fail on a failed import! (the form
        # simply yields no results) — verify the libs up front or the eval
        # would silently return unevaluated garbage
        if not os.path.isfile(os.path.join(lib_dir, lib)):
            return f"metta_error: vendored metta lib missing: {os.path.join(lib_dir, lib)}", False

    program_file = _write_program_file(_build_program(expr, lib_dir))
    try:
        try:
            code, out, err = _run_swipl(program_file)
        except FileNotFoundError as exc:
            return f"metta_error: swipl runtime unavailable: {exc}", False
        except subprocess.TimeoutExpired:
            return f"metta_error: swipl timeout after {SWIPL_TIMEOUT_S}s", False
        if code != 0:
            return f"metta_error: swipl exited {code}: {_error_excerpt(err, out)}", False
    finally:
        try:
            os.unlink(program_file)
        except OSError:
            pass

    result_lines = _filter_output(out)
    return ("\n".join(result_lines) if result_lines else "()", True)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: metta_run.py '<s-expression>'", file=sys.stderr)
        return 2
    output, _ok = run_expression(argv[0])
    # R-S8: the working-memory ledger episode (best-effort)
    _append_history_episode("eval", argv[0][:120], output.replace("\n", " "))
    # handled statuses (incl. syntax_error) exit 0 — the printed line IS
    # the contract result (never raises; failures surface as status
    # strings); only usage errors exit nonzero
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
