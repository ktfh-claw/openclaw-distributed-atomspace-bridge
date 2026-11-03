#!/usr/bin/env python3
"""Evaluate ONE MeTTa s-expression with the vendored hyperon runtime.

The OpenClaw-SUT "teach OpenClaw MeTTa" skill's runtime wrapper (spec
R-S3): each invocation loads the vendored NAL/PLN libraries
(``lib_nal.metta`` + ``lib_pln.metta``, verbatim from the pinned MeTTa
runtime image) into a FRESH EPHEMERAL atomspace, evaluates ONE
s-expression, and prints the interpreter output (MeTTa repr — the
derived atoms with their ``(stv s c)`` truth values). Atomspace is
EPHEMERAL between calls, matching the Omega runtime: nothing persists
across invocations.

Usage:
    metta_run.py '<s-expression>'

The leading ``!`` eval prefix is optional (omitted in the skill contract;
prepended mechanically). The wrapped invocation form
``(metta "(...)")`` is accepted and unwrapped mechanically, mapping the
skill call to this script.

Output:
- success: the interpreter's result atoms, one per line, in MeTTa
  syntax (e.g. ``((--> garfield mammal) (stv 1.0 0.9))``); an empty
  result prints ``()``
- syntax/shape errors: ``syntax_error: <detail>`` (exit 1) — read the
  offending form, fix the shape (almost always argument count or
  arity), retry once
- any other failure: a ``metta_error: <detail>`` status line (exit 1)

R-S8: an episode line (``; <iso> metta <summary>`` + the verbatim call
and result) is appended to ``<workspace>/history.metta`` — best-effort.

Environment:
    OPENCLAW_SUT_METTA_LIB_DIR   vendored libs dir (default /opt/sut-metta)
    OPENCLAW_SUT_WORKSPACE       workspace root (default: cwd)

The module never raises; failures surface as printed status strings.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LIB_DIR = "/opt/sut-metta"
LIB_NAL = "lib_nal.metta"
LIB_PLN = "lib_pln.metta"
MAX_EXPR_CHARS = 4096


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


def _fmt_result(value) -> str:
    """MeTTa repr of one interpreter result value (atom or nested list)."""
    if isinstance(value, (list, tuple)):
        return "(" + " ".join(_fmt_result(v) for v in value) + ")"
    rep = repr(value)
    return rep if rep else str(value)


def _load_libs(metta) -> None:
    """Load the vendored NAL/PLN libs into the fresh atomspace (spec
    order: lib_nal.metta then lib_pln.metta). Files that are absent or
    unreadable abort with a clear status — the smoke gate verifies the
    libs land in the image (R-D2/R-D1 stage 10)."""
    lib_dir = Path(_env_get("OPENCLAW_SUT_METTA_LIB_DIR", DEFAULT_LIB_DIR))
    for lib in (LIB_NAL, LIB_PLN):
        path = lib_dir / lib
        if not path.is_file():
            raise FileNotFoundError(str(path))
        text = path.read_text(encoding="utf-8")
        if text.strip():
            metta.run(text)


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

    try:
        from hyperon import Metta  # the vendored runtime (Dockerfile.sut)
    except Exception as exc:  # ImportError at smoke time = image defect
        return f"metta_error: hyperon runtime unavailable: {exc}", False

    metta = Metta()  # FRESH ephemeral atomspace per invocation
    try:
        _load_libs(metta)
    except FileNotFoundError as exc:
        return f"metta_error: vendored metta lib missing: {exc}", False
    except Exception as exc:
        return f"syntax_error: lib load failed: {exc}", False

    program = "!" + expr  # eval-prefixed: execute, not just parse
    try:
        results = metta.run(program)
    except Exception as exc:
        return f"syntax_error: {exc}", False

    lines = [_fmt_result(r) for r in results]
    return ("\n".join(lines) if lines else "()"), True


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: metta_run.py '<s-expression>'", file=sys.stderr)
        return 2
    output, _ok = run_expression(argv[0])
    # R-S8: the working-memory ledger episode (best-effort)
    _append_history_episode("eval", argv[0][:120], output)
    # handled statuses (incl. syntax_error) exit 0 — the printed line IS
    # the contract result (never raises; failures surface as status
    # strings); only usage errors exit nonzero
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
