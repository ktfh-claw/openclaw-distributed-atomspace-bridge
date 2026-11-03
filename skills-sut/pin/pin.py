#!/usr/bin/env python3
"""Pin a string as working memory — the pinned-ledger writer.

OpenClaw-SUT port of the pin skill (spec R-S4): appends the text (one
line) to ``benchmark/pinned-ledger.md`` under the workspace root and
confirms. The pinned ledger is the cross-cycle working memory: it
survives wake cycles within an agent run (a file — unlike a tool
result, which is gone next cycle), and the LAST line is the current
state; earlier lines are stale history.

Pinning the same text twice is a no-op (duplicate of the current last
line is skipped) — the same dedup semantics as the prompt-extension pin
this ports.

Usage:
    pin.py '<text>'

Output:
- ``PIN-OK: benchmark/pinned-ledger.md:<n>`` — appended; n = total
  lines in the ledger after the append
- ``PIN-OK: duplicate pin (no-op)`` — the text equals the current last
  line; nothing was appended
- ``PIN-FAILED: <reason>`` — the append failed; NEVER claim a pin that
  did not land

Environment:
    OPENCLAW_SUT_WORKSPACE    workspace root (default: cwd)

The module never raises; failures surface as printed status strings.
"""

from __future__ import annotations

import os
import sys

LEDGER_REL = os.path.join("benchmark", "pinned-ledger.md")
MAX_PIN_CHARS = 4096


def _workspace_root() -> str:
    return os.environ.get("OPENCLAW_SUT_WORKSPACE", "") or os.getcwd()


def pin(text: str) -> str:
    """Append the text as one ledger line; return the status string."""
    if not isinstance(text, str) or not text.strip():
        return "PIN-FAILED: empty pin text"
    if len(text) > MAX_PIN_CHARS:
        return f"PIN-FAILED: pin text exceeds {MAX_PIN_CHARS} characters"
    line = " ".join(text.split())  # ONE line: collapse embedded newlines
    path = os.path.join(_workspace_root(), LEDGER_REL)
    last = ""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
            last = lines[-1] if lines else ""
        if line == last:
            return "PIN-OK: duplicate pin (no-op)"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        with open(path, "r", encoding="utf-8") as f:
            n = len([ln for ln in f.read().splitlines() if ln.strip()])
        return f"PIN-OK: {LEDGER_REL.replace(os.sep, '/')}:{n}"
    except OSError as exc:
        return f"PIN-FAILED: {exc}"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: pin.py '<text>'", file=sys.stderr)
        return 2
    status = pin(argv[0])
    # handled statuses (incl. PIN-FAILED) exit 0 — the printed line IS
    # the contract result; only usage errors exit nonzero
    print(status)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
