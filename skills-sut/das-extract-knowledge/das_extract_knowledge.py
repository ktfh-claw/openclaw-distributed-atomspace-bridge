#!/usr/bin/env python3
"""Checkpoint manifest writer for the das-extract-knowledge skill.

OpenClaw-SUT port of the Omega plugin helper
(deploy/omega/plugins/das-extract-knowledge/das_extract_knowledge.py):
the checkpoint manifest is the phase boundary between the extraction
and reasoning phases — the extraction phase writes it (recording the
extracted predicates, their write receipts/handles, sources, and a
timestamp), and the reasoning phase reads it as its entry point into
the knowledge base. Contracts ported, not the plugin machinery: the
Omega memory-volume path (/PeTTa/repos/Omega/memory/knowledge-checkpoints)
is replaced by the workspace-relative convention — the ONLY mechanical
de-Omega'ing.

Path convention: <workspace>/knowledge-checkpoints/<corpus-id>.md (one
manifest per corpus, append-only across runs).

Usage:
    das_extract_knowledge.py '{"action": "checkpoint", "corpus": "<id>", "predicates": [{"expression": "...", "handle": "...", "source": "..."}]}'

Actions:
- "checkpoint": append the manifest data (predicates + receipts +
  sources + timestamp) to the checkpoint manifest for the corpus.
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
from datetime import datetime, timezone
from typing import Any

CHECKPOINT_DIR_REL = "knowledge-checkpoints"

# Size limits for the manifest data (ported from the Omega helper).
MAX_MANIFEST_BYTES = 256 * 1024
MAX_PREDICATES = 1024
MAX_EXPRESSION_CHARS = 2048
MAX_HANDLE_CHARS = 256
MAX_SOURCE_CHARS = 480


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


def _manifest_path(corpus_id: str) -> str:
    """Return the manifest path for a corpus ID."""
    # Sanitize the corpus ID (no path separators, no whitespace).
    safe = "".join(c for c in corpus_id if c.isalnum() or c in "-_")
    return os.path.join(_checkpoint_dir(), f"{safe}.md")


def _format_manifest_entry(predicate: dict[str, Any]) -> str:
    """Format a predicate entry for the manifest."""
    expression = predicate.get("expression", "")
    handle = predicate.get("handle", "")
    source = predicate.get("source", "")
    return f"expr {expression} top={handle} ref={source}"


def handle(body: Any) -> str:
    """Handle a das-extract-knowledge skill invocation.

    Actions:
    - "checkpoint": append the manifest data (predicates + receipts +
      sources + timestamp) to the checkpoint manifest for the corpus.
    - "describe": return the procedure text (a pointer to the skill
      description).

    Returns a receipt string (never raises).
    """
    if not is_enabled():
        return "DAS-EXTRACT-KNOWLEDGE-FAILED: adapter is disabled"
    try:
        data = json.loads(body) if isinstance(body, str) else body
    except (ValueError, TypeError):
        return "DAS-EXTRACT-KNOWLEDGE-FAILED: invalid JSON body"

    if not isinstance(data, dict):
        return "DAS-EXTRACT-KNOWLEDGE-FAILED: invalid JSON body"

    action = data.get("action", "describe")

    if action == "describe":
        return ("See the das-extract-knowledge skill description for the "
                "full procedure (read corpus once, extract predicates, "
                "persist via das-write, write checkpoint manifest).")

    if action == "checkpoint":
        corpus_id = data.get("corpus", "")
        if not corpus_id or not isinstance(corpus_id, str):
            return "DAS-EXTRACT-KNOWLEDGE-FAILED: corpus ID required"

        predicates = data.get("predicates", [])
        if not isinstance(predicates, list):
            return "DAS-EXTRACT-KNOWLEDGE-FAILED: predicates must be a list"
        if len(predicates) > MAX_PREDICATES:
            return (f"DAS-EXTRACT-KNOWLEDGE-FAILED: predicates exceed "
                    f"{MAX_PREDICATES}")

        manifest_path = _manifest_path(corpus_id)
        try:
            os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        except OSError:
            return "DAS-EXTRACT-KNOWLEDGE-FAILED: could not create checkpoint directory"

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entries = []
        for p in predicates:
            if not isinstance(p, dict):
                continue
            expression = p.get("expression", "")
            handle_ = p.get("handle", "")
            source = p.get("source", "")
            if (not isinstance(expression, str)
                    or len(expression) > MAX_EXPRESSION_CHARS
                    or not isinstance(handle_, str)
                    or len(handle_) > MAX_HANDLE_CHARS
                    or not isinstance(source, str)
                    or len(source) > MAX_SOURCE_CHARS):
                return "DAS-EXTRACT-KNOWLEDGE-FAILED: predicate entry exceeds limits"
            entries.append(f"expr {expression} top={handle_} ref={source}")

        try:
            with open(manifest_path, "a", encoding="utf-8") as f:
                f.write(f"# Knowledge checkpoint: {corpus_id}\n")
                f.write(f"# Written: {timestamp}\n")
                for entry in entries:
                    f.write(entry + "\n")
        except OSError:
            return "DAS-EXTRACT-KNOWLEDGE-FAILED: could not write checkpoint manifest"

        return f"CHECKPOINT-WRITTEN: {manifest_path}"

    return "DAS-EXTRACT-KNOWLEDGE-FAILED: unknown action"


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) != 1:
        print('usage: das_extract_knowledge.py \'{"action": "checkpoint", ...}\'',
              file=sys.stderr)
        return 2
    # handled statuses (incl. FAILED) exit 0 — the printed line IS the
    # contract result; only usage errors exit nonzero
    print(handle(argv[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
