#!/usr/bin/env python3
"""CLI adapter for durable, verified DAS writes (OpenClaw-SUT skills port).

Port of the Omega das-write plugin core
(deploy/omega/plugins/das-write/das_write_bridge.py) to a standalone CLI
script invoked via the agent's exec tool. Contracts are ported, not the
Omega plugin machinery: the Omega config API (``config_get_by_key``) is
replaced by environment variables — the ONLY mechanical de-Omega'ing; the
v3/v4 shapes, require-ref semantics, size limits, error status strings and
the success receipt line are kept byte-for-byte:

    BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]

Usage:
    das_write_bridge.py '<metta-call>'

``<metta-call>`` is the skill string exactly as the task's reasoning
vocabulary writes it — either the bare form

    (add-atom &persistent (Fact ...) "https://source-url" (stv 0.9 0.8))

or the wrapped invocation form ``(metta "(add-atom ...)")`` (unwrapped
mechanically). Non-``&persistent`` expressions are NOT interception
targets: the script prints the empty-result marker ``()`` (fall through
to stock evaluation is the caller's decision).

OpenClaw-SUT additions over the Omega plugin (spec R-S1/R-S8):
  - on a successful write the receipt line is ALSO appended, ISO-8601-
    prefixed, to ``<workspace>/benchmark/persist-receipts.log`` (the
    harness receipts-sidecar census lane) — best-effort, NEVER fails
    the write;
  - an episode line is appended to ``<workspace>/history.metta`` (the
    working-memory ledger) — best-effort.

Environment:
    OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN  write-bridge origin (exact http
                                      origin with an explicit port)
    OPENCLAW_SUT_READ_PROXY_ORIGIN    read-proxy origin (recorded for
                                      parity with the skill contract)
    OPENCLAW_SUT_WORKSPACE            workspace root (default: cwd)
    OPENCLAW_SUT_DAS_ENABLED          "1" enables the bridge (opt-in,
                                      same gate discipline as the Omega
                                      adapter)
    OPENCLAW_SUT_WRITE_REQUIRE_REF    "1" (default) requires a source
                                      reference on persistent writes
    OPENCLAW_SUT_WRITE_SOURCE_ROOTS   allowed absolute-path roots for
                                      path source refs (comma/whitespace
                                      separated; empty = URL refs only)

The module never raises; all failures surface as printed status strings
(byte-identical to the Omega plugin contract).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

# Write-bridge facade paths (deployed on the omega-das-integration-client
# docker network; the origin comes from the environment).
DEFAULT_ORIGIN = "http://write-bridge:8080"

WRITE_PATH = "/v1/write"
SOURCE_PATH = "/v1/source"

# Size limit for the metta expression (mirrors WRITE_MAX_METTA_CHARS).
MAX_METTA_CHARS = 2048

# v3 provenance suffix limits.
MAX_REF_CHARS = 480
MAX_FETCH_CHARS = 2_000_000
FETCH_TIMEOUT_SECONDS = 20

_TEXT_CONTENT_PREFIXES = ("text/",)
_TEXT_CONTENT_TYPES = ("application/json", "application/xml", "application/xhtml+xml", "application/javascript")

# Bounded response read (64 KiB).
MAX_RESPONSE_BYTES = 64 * 1024

# Request timeout for the facade POST.
REQUEST_TIMEOUT_SECONDS = 15

# Status prefixes.
STATUS_OK = "BRIDGE-PERSIST-OK"
STATUS_WRITE_FAILED = "BRIDGE-PERSIST-WRITE-FAILED"
STATUS_REMOVE_UNSUPPORTED = "BRIDGE-PERSIST-REMOVE-UNSUPPORTED"

# v2 rejection (pinned status string).
GIT_REJECTED = "git citations are no longer accepted — pass the source reference; archiving is automatic"
BAD_REF = "source ref must be an http(s) URL or an allowed absolute path (≤480 chars, no whitespace)"

# v1 rejection under the require-ref gate (pinned status reason).
REF_REQUIRED = "a source reference is required on persistent writes — append the source URL or allowed path after the expression, e.g. (add-atom &persistent <expr> \"<ref>\")"

# Per-process source cache: ref -> {"sha256": <64hex>, "commit": <40hex>}.
# A cache hit skips BOTH the source fetch and the ledger append; dedup on
# the facade makes cross-process re-POSTs idempotent end-to-end.
_source_cache: dict[str, dict[str, str]] = {}


def _env_get(name: str, default: str = "") -> str:
    """The environment-only replacement for the Omega config API."""
    value = os.environ.get(name, "")
    return value if isinstance(value, str) else default


def is_enabled() -> bool:
    """Return true only for the single explicit opt-in value (the Omega
    adapter's OMEGA_DAS_ENABLED gate, mechanically de-Omega'd)."""
    return _env_get("OPENCLAW_SUT_DAS_ENABLED", "") == "1"


def _require_ref() -> bool:
    """Return true when the require-ref gate is set. The SUT deployment
    DEFAULTS to required (the benchmark arm's discipline: every durable
    write carries provenance); set OPENCLAW_SUT_WRITE_REQUIRE_REF=0 to
    open the v1 suffix-less shape."""
    return _env_get("OPENCLAW_SUT_WRITE_REQUIRE_REF", "1") != "0"


def _workspace_root() -> str:
    """The agent workspace root (artifact paths are workspace-relative)."""
    return _env_get("OPENCLAW_SUT_WORKSPACE", "") or os.getcwd()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_receipt_sidecar(receipt: str) -> None:
    """R-S1 addition: append the receipt line, ISO-8601-prefixed, to
    benchmark/persist-receipts.log under the workspace root. BEST-EFFORT:
    a failure to append must NOT fail the write (the docker-log census
    remains the primary source)."""
    try:
        path = os.path.join(_workspace_root(), "benchmark",
                            "persist-receipts.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{_now_iso()} {receipt}\n")
    except OSError:
        pass


def _append_history_episode(op: str, summary: str, call: str,
                            result: str) -> None:
    """R-S8: append an episode line (``; <iso> <op> <summary>`` + the
    verbatim call and result) to history.metta at the workspace root.
    BEST-EFFORT: the ledger stays current but an append failure never
    fails the operation."""
    try:
        path = os.path.join(_workspace_root(), "history.metta")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"; {_now_iso()} {op} {summary}\n")
            f.write(f"{call} => {result}\n")
    except OSError:
        pass


def _validate_origin(origin: str) -> str:
    """Validate the origin; return the /v1/write endpoint URL."""
    if not isinstance(origin, str) or not origin or origin.strip() != origin:
        raise ValueError("write origin is not canonical")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("write origin is invalid") from exc
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.netloc != f"{parsed.hostname}:{port}"
        or origin != f"http://{parsed.hostname}:{port}"
    ):
        raise ValueError("write origin must be an exact http origin with an explicit port")
    return origin + WRITE_PATH


def _balanced_span(text: str) -> tuple[int, int] | None:
    """Return the (start, end) span of the first balanced expression in text.

    ``text`` is the text after the ``&persistent`` token. The span is
    found by string-aware paren counting: an expression is balanced when
    its paren depth reaches zero (quotes inside the expression are
    respected; a quote inside the expression starts/ends a string and
    does not count toward the paren depth).
    """
    start = text.find("(")
    if start < 0:
        return None
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
        elif ch == '"':
            # Skip quoted string (with escape awareness).
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 1
                    if i < n:
                        i += 1
                    continue
                if text[i] == '"':
                    break
                i += 1
        i += 1
    return None


def _scan_quoted_string(text: str, start: int) -> tuple[str, int] | None:
    """Scan a double-quoted string starting at ``start`` (must be a quote).

    Returns (unquoted_value, end_index_exclusive) or None when the text
    at ``start`` is not a quote or the string is unterminated. Escape
    sequences ``\\`` and ``\\"`` are preserved verbatim in the value
    (MeTTa string semantics; the facade receives the raw quoted token).
    """
    if start >= len(text) or text[start] != '"':
        return None
    i = start + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            return (text[start : i + 1], i + 1)
        i += 1
    return None


def _parse_stv(text: str, start: int) -> tuple[tuple[float, float], int] | None:
    """Parse a ``(stv <strength> <confidence>)`` form starting at ``start``.

    Returns ((strength, confidence), end_index_exclusive) or None when
    the text at ``start`` is not that exact shape.
    """
    prefix = "(stv"
    if not text.startswith(prefix, start):
        return None
    rest = text[start + len(prefix) :]
    if not rest or rest[0] not in (" ", "\t", "\n"):
        return None
    close = rest.find(")")
    if close < 0:
        return None
    inner = rest[:close].split()
    if len(inner) != 2:
        return None
    try:
        strength = float(inner[0])
        confidence = float(inner[1])
    except ValueError:
        return None
    if not (0.0 <= strength <= 1.0 and 0.0 <= confidence <= 1.0):
        return None
    return (strength, confidence), start + len(prefix) + close + 1


def _parse_suffix(remainder: str) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """Parse the optional v3 provenance suffix after the fact expression.

    ``remainder`` is the text between the end of the balanced fact
    expression and the add-atom wrapper's closing paren (the caller has
    NOT yet stripped the closing paren; it must be the last non-space
    character). Returns (ref, tv, error) — ref/tv are None when absent;
    error is a status reason string on shape violations.
    """
    i = 0
    n = len(remainder)
    ref: str | None = None
    tv: dict[str, Any] | None = None

    def skip_ws(idx: int) -> int:
        while idx < n and remainder[idx] in (" ", "\t", "\n", "\r"):
            idx += 1
        return idx

    i = skip_ws(i)
    # Optional quoted source ref.
    scanned = _scan_quoted_string(remainder, i)
    if scanned is not None:
        token, i = scanned
        value = token[1:-1]
        if value.startswith("git:"):
            return None, None, GIT_REJECTED
        if value.startswith(("http://", "https://", "/")):
            if len(value) > MAX_REF_CHARS or any(ch.isspace() for ch in value):
                return None, None, BAD_REF
            ref = value
        else:
            return None, None, BAD_REF
        i = skip_ws(i)
        # A second quoted token is only possible in the retired v2 shape
        # (url + git citation) — both halves are rejected.
        scanned = _scan_quoted_string(remainder, i)
        if scanned is not None:
            token2, _ = scanned
            if token2[1:-1].startswith("git:"):
                return None, None, GIT_REJECTED
            return None, None, "unexpected content after the source reference"
    # Optional (stv strength confidence).
    parsed = _parse_stv(remainder, i)
    if parsed is not None:
        (strength, confidence), i = parsed
        tv = {"strength": strength, "confidence": confidence}
        i = skip_ws(i)
    # Only the add-atom closing paren may remain.
    if i >= n or remainder[i] != ")" or remainder[i + 1 :].strip():
        return None, None, "unexpected content after the source reference"
    return ref, tv, None


def _allowed_path_roots() -> list[str]:
    """Parse the OPENCLAW_SUT_WRITE_SOURCE_ROOTS env (comma/whitespace
    separated) — the Omega dasWriteSourceRoots config key, mechanically
    de-Omega'd."""
    raw = _env_get("OPENCLAW_SUT_WRITE_SOURCE_ROOTS", "")
    if not isinstance(raw, str):
        return []
    return [root for root in re.split(r"[\s,]+", raw.strip()) if root]


def _resolve_source(ref: str) -> tuple[str, str | None]:
    """Resolve a source ref to its content; return (content, None) or (None, error).

    URL refs are fetched with the bounded fetch (User-Agent header, 20 s
    timeout, 2,000,000 character cap, text-only content types). Absolute
    path refs are allowed only when source roots are configured and
    ``realpath(ref)`` resolves inside one of them; the file is read with
    the same cap. Never raises.
    """
    if ref.startswith(("http://", "https://")):
        try:
            request = urllib.request.Request(
                ref,
                headers={"User-Agent": "openclaw-sut-agent/1.0 (+provenance-archiver)"},
            )
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    return None, f"source fetch failed (HTTP {response.status})"
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if not (
                    content_type.startswith(_TEXT_CONTENT_PREFIXES)
                    or content_type in _TEXT_CONTENT_TYPES
                    or content_type == ""
                ):
                    return None, f"unsupported content type {content_type or 'unknown'} (text only)"
                raw = response.read(MAX_FETCH_CHARS + 1)
                if len(raw) > MAX_FETCH_CHARS:
                    return None, "source exceeds the 2,000,000 character limit"
            content = raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return None, f"source fetch failed (HTTP {exc.code})"
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return None, "fetch timed out"
            return None, f"source fetch failed ({exc.reason})"
        except (TimeoutError, socket.timeout):
            return None, "fetch timed out"
        except Exception:
            return None, "source fetch failed"
        if not content.strip():
            return None, "source content empty"
        return content, None

    # Absolute container path: allowed only within the configured roots.
    roots = _allowed_path_roots()
    try:
        real = os.path.realpath(ref)
    except (OSError, ValueError):
        return None, "source path outside the configured roots (OPENCLAW_SUT_WRITE_SOURCE_ROOTS)"
    inside = any(
        real == root.rstrip("/") or real.startswith(root.rstrip("/") + "/")
        for root in roots
        if root
    )
    if not inside:
        return None, "source path outside the configured roots (OPENCLAW_SUT_WRITE_SOURCE_ROOTS)"
    try:
        with open(real, "rb") as f:
            raw = f.read(MAX_FETCH_CHARS + 1)
        if len(raw) > MAX_FETCH_CHARS:
            return None, "source exceeds the 2,000,000 character limit"
        content = raw.decode("utf-8", errors="replace")
    except (IOError, OSError):
        return None, f"source unreadable at {ref}"
    if not content.strip():
        return None, "source content empty"
    return content, None


def _post_source(origin_base: str, ref: str, sha256: str) -> tuple[str, str | None]:
    """Append (ref, sha256) to the ledger via POST /v1/source.

    Returns (commit, None) or (None, error) where the error is the inner
    facade reason for the ``ledger append failed (...)`` status.
    """
    request = urllib.request.Request(
        origin_base + SOURCE_PATH,
        data=json.dumps({"ref": ref, "sha256": sha256}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return None, "response exceeds 64 KiB"
            result = json.loads(body)
            if not isinstance(result, dict) or not isinstance(result.get("commit"), str) or not result["commit"]:
                return None, "invalid response from facade"
            return result["commit"], None
    except urllib.error.HTTPError as exc:
        try:
            error_json = json.loads(exc.read())
            error_field = error_json.get("error") if isinstance(error_json, dict) else None
            if error_field:
                return None, str(error_field)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
        return None, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return None, "request timed out"
        return None, "request failed"
    except (TimeoutError, socket.timeout):
        return None, "request timed out"
    except json.JSONDecodeError:
        return None, "invalid JSON response"
    except Exception:
        return None, "request failed"


def _unwrap_metta_call(text: str) -> str:
    """Mechanically map the invocation form ``(metta "(add-atom ...)")`` to
    the bare add-atom skill string (the quoted payload is unescaped)."""
    stripped = text.strip()
    if not stripped.startswith("(metta "):
        return stripped
    scanned = _scan_quoted_string(stripped[len("(metta "):].lstrip(), 0)
    if scanned is None:
        return stripped
    token, _ = scanned
    try:
        return json.loads(token)
    except json.JSONDecodeError:
        return token[1:-1].replace('\\"', '"')


def intercept(text: Any) -> list[str]:
    """Intercept the skill string; return [] for fall-through, [status] for handled."""
    if not is_enabled():
        return []
    if not isinstance(text, str) or not text.strip():
        return []

    stripped = _unwrap_metta_call(text)
    # Tolerate one optional leading "!" prefix character followed by
    # whitespace (the eval prefix on some skill strings).
    if stripped.startswith("!"):
        stripped = stripped[1:].lstrip()

    # Check for (add-atom or (remove-atom prefix (case-sensitive).
    for marker in ("add-atom", "remove-atom"):
        prefix = f"({marker}"
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix):].lstrip()
        # After (add-atom or (remove-atom, expect whitespace, then
        # the exact token &persistent, then whitespace.
        if not rest.startswith("&persistent"):
            continue
        # Exact token check: &persistent must be followed by whitespace.
        after_persistent = rest[len("&persistent"):]
        if not after_persistent or after_persistent[0] not in (" ", "\t", "\n"):
            continue
        # Interception target detected.
        if marker == "remove-atom":
            return [STATUS_REMOVE_UNSUPPORTED + ": remove-atom &persistent is not bridged yet; nothing was removed from DAS"]
        # add-atom path: the remainder after &persistent must start with
        # exactly ONE balanced expression (string-aware paren counting)
        # optionally followed by the v3 provenance suffix.
        remainder = after_persistent[1:].lstrip()  # skip the whitespace char
        span = _balanced_span(remainder)
        if span is None:
            return [STATUS_WRITE_FAILED + ": expected one balanced expression after &persistent"]
        expr = remainder[span[0]:span[1]]
        after_expr = remainder[span[1]:]
        # v1 shape: nothing but the closing paren after the expression.
        if after_expr.strip() == ")":
            # require-ref gate: a suffix-less write reaches DAS with no
            # provenance attrs and no ledger commit — reject BEFORE the
            # size check so the actionable guidance always wins.
            if _require_ref():
                return [STATUS_WRITE_FAILED + ": " + REF_REQUIRED]
            # Payload size check.
            if len(expr) > MAX_METTA_CHARS:
                return [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
            return _post_to_facade(expr)
        # v3 shape: provenance suffix before the closing paren.
        if after_expr.strip() == "":
            return [STATUS_WRITE_FAILED + ": missing add-atom closing paren"]
        ref, tv, error = _parse_suffix(after_expr)
        if error is not None:
            return [STATUS_WRITE_FAILED + ": " + error]
        # stv-alone suffix parses to ref=None — the same require-ref
        # gate, again BEFORE the size check so the guidance wins.
        if ref is None and _require_ref():
            return [STATUS_WRITE_FAILED + ": " + REF_REQUIRED]
        if len(expr) > MAX_METTA_CHARS:
            return [STATUS_WRITE_FAILED + ": expression exceeds 2048 characters"]
        return _post_to_facade(expr, ref=ref, tv=tv)
    # Not a target — fall through to stock MeTTa eval.
    return []


def _post_to_facade(
    payload: str,
    ref: str | None = None,
    tv: dict[str, Any] | None = None,
) -> list[str]:
    """POST the payload to the write-bridge facade; return [status].

    v3 (``ref`` given): resolve the source, sha256 it, ledger-append via
    POST /v1/source (unless cached), then POST /v1/write with the
    provenance payload ``{ref, git_commit, blob_sha256}``.
    """
    if ref is None and _require_ref():
        # Defensive double gate: intercept() rejects suffix-less writes
        # under the require-ref gate before the size checks; this guard
        # keeps the invariant local to the POSTing function in case a
        # future caller bypasses intercept().
        return [STATUS_WRITE_FAILED + ": " + REF_REQUIRED]
    origin = _env_get("OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN", DEFAULT_ORIGIN)
    try:
        endpoint = _validate_origin(origin)
    except ValueError:
        return [STATUS_WRITE_FAILED + ": invalid OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN"]
    origin_base = endpoint[: -len(WRITE_PATH)]

    provenance: dict[str, Any] | None = None
    if ref is not None:
        cached = _source_cache.get(ref)
        if cached is not None:
            sha256 = cached["sha256"]
            commit = cached["commit"]
        else:
            content, error = _resolve_source(ref)
            if error is not None:
                return [STATUS_WRITE_FAILED + ": " + error]
            sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            commit, error = _post_source(origin_base, ref, sha256)
            if error is not None:
                return [STATUS_WRITE_FAILED + f": ledger append failed ({error})"]
            _source_cache[ref] = {"sha256": sha256, "commit": commit}
        provenance = {"ref": ref, "git_commit": "git:" + commit, "blob_sha256": sha256}

    body: dict[str, Any] = {"metta": payload, "verify": True}
    if provenance is not None:
        body["provenance"] = provenance
    if tv is not None:
        body["tv"] = tv
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return [STATUS_WRITE_FAILED + ": response exceeds 64 KiB"]
            payload_json = json.loads(body)
            if not isinstance(payload_json, dict):
                return [STATUS_WRITE_FAILED + ": invalid response from facade"]
            if payload_json.get("verified") is True:
                handles = payload_json.get("handles") or []
                n = len(handles)
                top_handle = payload_json.get("top_handle")
                if not isinstance(top_handle, str) or not top_handle:
                    return [STATUS_WRITE_FAILED + ": invalid response from facade"]
                status = STATUS_OK + f": verified={n} top={top_handle}"
                if tv is not None:
                    status += f" stv=({tv['strength']},{tv['confidence']})"
                # R-S1: the receipts sidecar (best-effort — a failure to
                # append NEVER fails the verified write)
                _append_receipt_sidecar(status)
                return [status]
            elif payload_json.get("verified") is False:
                missing = payload_json.get("missing") or []
                joined = ",".join(str(h) for h in missing)
                return [STATUS_WRITE_FAILED + f": written but read-back verification missing handles: {joined}"]
            else:
                return [STATUS_WRITE_FAILED + ": invalid response from facade"]
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read()
            error_json = json.loads(error_body)
            error_field = error_json.get("error") if isinstance(error_json, dict) else None
            if error_field:
                return [STATUS_WRITE_FAILED + f": {error_field}"]
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
        return [STATUS_WRITE_FAILED + f": HTTP {exc.code}"]
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return [STATUS_WRITE_FAILED + ": request timed out"]
        return [STATUS_WRITE_FAILED + ": request failed"]
    except (TimeoutError, socket.timeout):
        return [STATUS_WRITE_FAILED + ": request timed out"]
    except json.JSONDecodeError:
        return [STATUS_WRITE_FAILED + ": invalid JSON response"]
    except Exception:
        return [STATUS_WRITE_FAILED + ": request failed"]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: das_write_bridge.py '<metta-call>'", file=sys.stderr)
        return 2
    statuses = intercept(argv[0])
    if not statuses:
        # not an interception target: fall-through marker (stock MeTTa
        # evaluation is the caller's decision)
        print("()")
        return 0
    # R-S8: the working-memory ledger episode — the verbatim skill call
    # and its result, on EVERY handled add-atom operation (success or
    # failure — the ledger stays current; best-effort)
    _append_history_episode("das-write", "persist", argv[0], statuses[0])
    print(statuses[0])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
