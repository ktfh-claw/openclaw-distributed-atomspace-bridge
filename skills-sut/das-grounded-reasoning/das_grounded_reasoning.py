#!/usr/bin/env python3
"""Checkpoint manifest reader for the das-grounded-reasoning skill.

OpenClaw-SUT port of the Omega plugin helper
(deploy/omega/plugins/das-grounded-reasoning/das_grounded_reasoning.py):
reads the checkpoint manifest (the phase boundary between the
extraction and reasoning phases) as the reasoning entry point into the
knowledge base — the predicates verbatim. Contracts ported, not the
plugin machinery: the Omega memory-volume path
(/PeTTa/repos/Omega/memory/knowledge-checkpoints) is replaced by the
workspace-relative convention — the ONLY mechanical de-Omega'ing.

Path convention: <workspace>/knowledge-checkpoints/<corpus-id>.md (one
manifest per corpus, append-only across runs).

Usage:
    das_grounded_reasoning.py '{"action": "read_checkpoint"}'
    das_grounded_reasoning.py '{"action": "read_checkpoint", "corpus": "<id>"}'

Actions:
- "read_checkpoint": read the checkpoint manifest (latest or by corpus
  ID) and return its content (predicates verbatim).
- "describe": return the procedure text (a pointer to the skill
  description).

Environment:
    OPENCLAW_SUT_WORKSPACE    workspace root (default: cwd)
    OPENCLAW_SUT_DAS_ENABLED  "1" enables the helper (opt-in)

The module never raises; failures surface as printed status strings.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

CHECKPOINT_DIR_REL = "knowledge-checkpoints"
MAX_MANIFEST_CHARS = 256 * 1024


def _env_get(name: str, default: str = "") -> str:
    value = os.environ.get(name, "")
    return value if isinstance(value, str) else default


def is_enabled() -> bool:
    """Return True iff OPENCLAW_SUT_DAS_ENABLED == 1 (same gate as the
    Omega helper's OMEGA_DAS_ENABLED, mechanically de-Omega'd)."""
    return _env_get("OPENCLAW_SUT_DAS_ENABLED", "") == "1"


def _checkpoint_dir() -> str:
    """The checkpoint manifest directory under the workspace root."""
    return os.path.join(_env_get("OPENCLAW_SUT_WORKSPACE", "") or os.getcwd(),
                        CHECKPOINT_DIR_REL)


def _latest_manifest() -> str | None:
    """Return the latest checkpoint manifest path (mtime-desc), or None."""
    checkpoint_dir = _checkpoint_dir()
    try:
        files = [f for f in os.listdir(checkpoint_dir) if f.endswith(".md")]
    except OSError:
        return None
    if not files:
        return None
    # Sort by mtime, descending.
    files.sort(key=lambda f: os.path.getmtime(os.path.join(checkpoint_dir, f)), reverse=True)
    return os.path.join(checkpoint_dir, files[0])


def _manifest_path(corpus_id: str) -> str:
    """Return the manifest path for a corpus ID."""
    safe = "".join(c for c in corpus_id if c.isalnum() or c in "-_")
    return os.path.join(_checkpoint_dir(), f"{safe}.md")


def handle(body: Any) -> str:
    """Handle a das-grounded-reasoning skill invocation.

    Actions:
    - "read_checkpoint": read the checkpoint manifest (latest or by
      corpus ID) and return its content (predicates verbatim).
    - "describe": return the procedure text (a pointer to the skill
      description).

    Returns the manifest content or an error string (never raises).
    """
    if not is_enabled():
        return "DAS-GROUNDED-REASONING-FAILED: adapter is disabled"
    try:
        data = json.loads(body) if isinstance(body, str) else body
    except (ValueError, TypeError):
        return "DAS-GROUNDED-REASONING-FAILED: invalid JSON body"

    if not isinstance(data, dict):
        return "DAS-GROUNDED-REASONING-FAILED: invalid JSON body"

    action = data.get("action", "describe")

    if action == "describe":
        return ("See the das-grounded-reasoning skill description for the "
                "full procedure (read checkpoint, formalize question, "
                "retrieve from DAS, answer strictly from stored facts).")

    if action == "read_checkpoint":
        corpus = data.get("corpus")
        if corpus:
            manifest_path = _manifest_path(corpus)
        else:
            manifest_path = _latest_manifest()
        if not manifest_path or not os.path.exists(manifest_path):
            return "DAS-GROUNDED-REASONING-FAILED: no checkpoint manifest found"
        try:
            with open(manifest_path, encoding="utf-8") as f:
                content = f.read(MAX_MANIFEST_CHARS + 1)
            if len(content) > MAX_MANIFEST_CHARS:
                return "DAS-GROUNDED-REASONING-FAILED: checkpoint manifest too large"
            return content
        except OSError:
            return "DAS-GROUNDED-REASONING-FAILED: could not read checkpoint manifest"

    return "DAS-GROUNDED-REASONING-FAILED: unknown action"


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) != 1:
        print('usage: das_grounded_reasoning.py \'{"action": "read_checkpoint"}\'',
              file=sys.stderr)
        return 2
    # handled statuses (incl. FAILED) exit 0 — the printed line IS the
    # contract result; only usage errors exit nonzero
    print(handle(argv[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
