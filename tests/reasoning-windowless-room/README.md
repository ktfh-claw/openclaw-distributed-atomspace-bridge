# Windowless Room Gating Test (v10)

## Purpose

Strict, deterministic **gating test** for the Omega agent's DAS-grounded reasoning governance. Not a scored benchmark: the test verifies that the environment is set up so the agent **answers query-first from DAS with provable provenance**, and it FAILS hard when it does not.

The test uses the classic "windowless room" prompt:

> "You are in a windowless room / attic in the dark. You turn on a bulb/lamp and look straight up. What do you see?"

**Expected correct answer:** The ceiling (or the lamp/bulb hanging from the ceiling). "The sky" is the pattern-match failure the test catches.

## The Gate (what a case must satisfy to PASS)

Every case must pass ALL four gates:

1. **A-gate (answer):** the `FINAL ANSWER (<case>)` line exists and is judged TRUE by one OpenAI chat-completions-compatible LLM call (`llm_judge.py`): a single prompt carrying the test question, the agent's answer line, and the expected correct answer; the endpoint replies TRUE/FALSE and the script parses it as the blocking gate. Endpoint configurable (`--judge-base-url/--judge-model/--judge-api-key/--judge-timeout`); defaults reuse the Omega agent's ASI:One `asi1-ultra` + `runtime.env` key. A judge failure emits blocking `A_JUDGE_UNAVAILABLE` — an unjudged answer never passes; preflight smoke-checks the judge. All other gates stay deterministic.
2. **Q-gate (query-first):** a REAL `das-retrieve` query was executed during the benchmark window (attested against history.metta snapshots), quoted in answers.md with its `DAS_RETRIEVE_OK ... count=<n>` receipt BEFORE the answer line, non-degenerate (≥1 `$variable` AND ≥1 non-variable literal — a quoted string or a bare content symbol; structural keywords like `Evaluation`/`Inheritance` do not count, and `$_` placeholders fail), and re-issued by the harness via the read-proxy with a matching count. The unsolvable case requires a quoted `count=0` absence probe that also re-issues at 0.
3. **E-gate (extraction):** knowledge-case FACTS lines exist and resolve verbatim against the extraction record (facts-index.md); first-case ingestion is receipt-proven; query literals reuse the extracted vocabulary.
4. **R-gate (reasoning trace):** the `REASONING:` line carries the formalized MeTTa reasoning trace — question clause (the executed query) first, verbatim extraction-record fact steps, optional derived conclusion over extracted vocabulary — semicolon-separated s-expressions, NOT generated prose (`R_NOT_METTA`). Unsolvable case keeps the trace shape but is exempt from index grounding.
5. **P-gate (provenance):** every `git:<sha> <url>` source citation resolves against the provenance git repo: commit exists → exactly one `sources/` blob + `index.jsonl` change → index entry at that commit matches the blob path → sha256(blob) matches the index entry → entry URL matches the citation. Knowledge cases with no SOURCES line fail.

Failure reasons are machine-readable condition codes (`A_MISSING`, `Q_NOT_IN_HISTORY`, `Q_PLACEHOLDER`, `Q_DEGENERATE_PATTERN`, `Q_REISSUE_MISMATCH`, `Q_ABSENCE_UNPROVEN`, `P_MISSING`, `P_UNRESOLVED:<COND>`, …) — see `grading.py` docstring.

## Files

- `background/*.md` — 5 background knowledge sources (spatial, lighting, perspective, meta-reasoning, failure-modes)
- `prompts/*.md` — the 7 prompt cases + expected-answer doc
- `facts.py` — canonical fact set (grading oracle, opt-in `--seed-canonical`), SOURCE_URLS, TEST_CASES
- `grading.py` — v5 strict gate: answers.md parsing (horizontal-whitespace-anchored line regexes), degenerate-query detection, MeTTa reasoning-trace parsing + grounding, gate_case + condition codes
- `history_parse.py` — benchmark-window extraction (pre/post snapshot prefix slicing), das-retrieve arg normalization (raw + JSON payload forms), placeholder/receipt/sha extraction
- `provenance_check.py` — citation → git repo resolution chain (mirrors the bridge's write-time verify_commit, read-only)
- `agent_prompt_template.md` — benchmark-mode prompt with the exact answers.md block format the gate parses
- `run_benchmark.py` — orchestrator CLI (phases: preflight|setup|agent|grade|report|teardown|full; `--agent-profile omega|openclaw`)
- `unit/` — 475 offline unit tests (stdlib shim runner: `python3 unit/run_tests.py`; includes the agent-profile seam suite `test_agent_profile.py`)
- `results/<run-id>/` — per-run artifacts (preflight/setup/agent/grade/report/teardown JSON + report.md)

## Exit Codes (the signal)

`grade`, `report`, and `full` return:

- `0` — gate PASS
- `2` — gate FAIL (expected negative signal: the environment did NOT meet the governance bar)
- `1` — harness/environment error (answers unreadable, no history window, etc.)

`full` ALWAYS runs teardown (even on gate FAIL) so the agent returns to standby.

## Offline Re-grade

`grade` supports `--answers-override`, `--history-override`, `--pre-snapshot-override`, `--post-snapshot-override` for re-grading archived runs without touching the live agent. A missing pre-benchmark snapshot is an error (window undefined → refuse to grade).

## --battery mode (oc3)

`full --battery battery` runs the 5 additional reasoning cases (the "manual reasoning questions") against the ALREADY-EXTRACTED live KB in DAS — **no shared extraction, no cleanup-das** (the live KB is reused and preserved for subsequent battery runs and the oc3 series). The preflight probes the read-proxy for a windowless-room fact and aborts the run when the KB is absent.

```bash
python3 run_benchmark.py full --battery battery --run-id <run-id> --agent-profile openclaw
```

The 5 battery cases (`facts.BATTERY_CASES`; same frozen grading gates and standards as the standard 3-case series):

| Case | What it probes |
|------|----------------|
| `stars-claim` | long-chain refutation (ceiling blocks the sky/stars + no natural light enters) |
| `floor-lamp` | light-source-position invariance (a floor lamp still leaves the ceiling as the look-up answer) |
| `burned-bulb` | state-change reasoning (bulb burns out — the ceiling is still the opaque surface above) |
| `stv-derivation` | stv derivation compliance (grounded `(|~ ...)` derivation with `(stv ...)` truth values, each premise DAS-receipt-verified) |
| `color-probe` | provenance-abuse negative probe (no color facts stored — a refusal is the correct answer; `required_facts = []`) |

Per-case flow identical to the standard per-case reasoning flow (reasoning-phase restart → answer wait → grade); per-case session ids reuse the oc2 pattern `wr-<run>-case-<case>`; results under `results/<run-id>/` with per-case grade JSONs + `grade.json` + `report.json`/`report.md`. `gate_verdict` PASS iff all 5 battery cases PASS. The on-disk extraction record (`facts-index.md`) is NOT reset — the battery reuses the live KB's record left by the prior extraction run; only `answers.md` starts fresh per battery run.

## Success Criteria

- All selected cases (3-case set: `original`, `unsolvable`, `false`) PASS the A/Q/E/R/P gate (exit 0)
- No fabricated queries (quoted query must exist in the benchmark-window history)
- No degenerate queries (placeholders, bare variables)
- Every citation resolves to the provenance git repo
- The unsolvable case proves absence (count=0, re-issued)
- Zero LLM interaction in the harness: grading is regex/keyword/HTTP/git only
- The REASONING: line carries a MeTTa reasoning trace grounded in DAS-retrieved facts (the campaign-grade standard), not generated prose

## Provenance

- v1 (benchmark): generated 2026-10-21; live run wr-2026-20261021-2355 graded 1/7 trace-PASS — all answers correct but no real das-retrieve calls
- v2 (gating test): 2026-10-22, per Balazs's directive — strict query-first gate, degenerate-trace conditions, provenance-resolves-to-git, deterministic grading
- v5 (reasoning-trace standard): 2026-10-24 — levers 1–2 rejected; R-gate (MeTTa trace, deterministic grounding), prompt step 4 (trace before answer write), line-anchored block parsing fix; 114 offline unit tests
- v6 (campaign-style fixed pipeline): 2026-10-24 19:50 UTC directive — deliverable-first prompt (reasoning trace + answer block on top), open-ended study step REMOVED (extraction = one unconditional bounded pass, record-driven skip); anti-loop rules; 8 new prompt-contract tests; 122 offline unit tests
- v7 (executed-reasoning standard): 2026-10-25 10:57 UTC directive — scenario A/A2 findings built in: `R_NOT_EXECUTED` gate (interpreter `(stv ...)` evidence required — `exec` record lines or trace-quoted stv; hand-composed truth values fail; unsolvable exempt), prompt step 4 EXECUTE THE REASONING (2-arg NAL/PLN contract via the metta-grammar plugin, exec-record discipline), step 5 deliverable-first write, STOP rule idle-silently discipline, preflight metta plugin checks (repo artifact + live mount); 127 offline unit tests
- v8 (pinned-ledger working memory): 2026-10-25 14:48 UTC directive — wr3g root cause (per-wake restarts collapse prior tool results to `$_` history tuples; each wake re-derived progress from file reads alone; 120/122 shell reads, zero DAS calls, header-only artifacts) fixed by the PINNED LEDGER: a mechanical `pin`-maintained ledger line (`LEDGER: step <1-5> | done: ... | next: <ONE literal tool call>`) is required cross-cycle working memory — pinned tool output is the only tool result that survives a wake; first-cycle seed = ledger pin with the literal archive-source call; each wake issues the `next:` call immediately instead of re-deriving from files; orientation reads bounded to one per cycle; terminal ledger line on completion; anti-loop unsure-resolution reroutes through the ledger. 136 offline unit tests (9 new v8 ledger-contract tests in `unit/test_v8_prompt.py`; v6 anti-loop invariant updated to the ledger routing).
- v9 (false-extraction-record visibility): 2026-10-25 20:44 UTC directive (wr3h close-out: push v7/v8; wr3i ①②③) — lever ① debug REFUTED the bridge round-trip hypothesis (fresh ar2/ar3/ar4 facade writes all retrieve; canary=4; agent-written lighting facts retrieve; the zero-result loop was TRUE ABSENCE: ~10 of ~23 recorded expressions — incl. the case-critical spatial facts — were never persisted, mongo holds zero nodes for their vocabulary); `parse_facts_index` accepts the agent's real record shapes (`expr` labels, trailing src/git annotations, receipt suffixes — balanced-prefix scan; wr3h graded facts_index_size=0 against a 3,067 B record); new informational `E_INDEXED_NOT_PERSISTED` presence cross-check (every recorded expression probed against DAS via last-element `$X` binding; absent ones listed per-expression); attestation lane always collected + `attested_retrieve_calls`/`attested_write_calls`/`attested_archive_calls` in grade JSON (history channel collapses to 100% `$_` placeholders); prompt step 1 = one `expr <expression> verified=<n>` line per fresh receipt, no batch recording; step 3 + anti-loop = count=0 twice-is-final bound with one re-persist allowance. 149 offline unit tests (13 new v9 gate tests incl. the real wr3h facts-index fixture).
- v10 (grader false-positive fixes): 2026-10-26 night directive (wr3i close-out: all 6 fired uncertainty-case conditions grader-side or harness-side) — (a) `A_SKY` negation-aware ("no window or sky visible" is the honest correct answer; an UNNEGATED sky/sun/stars mention still fails; negation must PRECEDE the claim, so "sky visible but no windows" still fails); (b) `Q_DEGENERATE_PATTERN` literal check accepts bare content symbols per its own docstring (the live working query `(--> (looking-up windowless-room) $X)` was rejected; structural keywords like `Evaluation`/`Inheritance` still do not count — `(Evaluation $X $Y)` remains a tautology probe); (c) `R_TRACE_NOT_GROUNDED` grounds executed-derivation steps ATOM-WISE (`(|- call premise) => output` splits into call + output atoms; whole-line comparison could never ground them; bare-symbol dialect grounds against the index/query bare-symbol vocabulary, fabricated atoms still fail); (d) attested-retrieve regex de-escaped to the facade pattern (the rf-string `HTTP/1\\.1" 2\\d\\d` demanded literal backslashes → the lane read 0 for every window containing real query traffic; proved by live repro on the wr3i 00:00:07.562Z agent query); (e) prompt gate-rules: cite each `git:<sha> <url>` pair EXACTLY as the archive receipt returned it (wr3i P_URL_MISMATCH ×2 diagnosed as agent-side mispairing: the agent shifted shas one position across source urls — wr3h receipts prove `3443aff`=perspective.md and `6149e59`=failure-modes.md, but the wr3i SOURCES line cited `6149e59`+perspective.md and `3443aff`+meta-reasoning.md). 169 offline unit tests (20 new v10 tests in `unit/test_v10_gates.py`).
- v11 (mid-trace grounding + memory-volume-relative prompt paths): 2026-10-26 night directive (wr3j close-out) — (a) `R_TRACE_NOT_GROUNDED` atom-wise grounding extended to EVERY non-first trace step (v10 applied it only to the final step; wr3j's MID-trace steps were executed-derivation outputs the interpreter produced — every atom grounded under the same literal/bare-symbol rule; step0 must still be the exact query clause; fabricated mid steps with new symbols still fail); (b) prompt-rendered artifact paths are MEMORY-VOLUME-RELATIVE (`repos/Omega/memory/benchmark/...`), not bare `benchmark/...` — the agent container's file tools resolve relative paths against cwd `/PeTTa` where no `benchmark` dir exists (volume mounted at `/PeTTa/repos/Omega/memory`); wr3j burned the case-1 window on 34+ APPEND-FAILED "file does not exist" loops before the agent self-worked-around; harness volume-side paths unchanged. 177 offline unit tests (8 new v11 tests: 4 gate + 4 prompt-path).
- Reference: windowless-room prompt (classic LLM failure case)
- v12 (FACTS-line verbatim-copy discipline): 2026-10-26 14:39 UTC directive (wr3k close-out — first-ever case-1 PASS; case 2 failed on E_FACTS_NOT_IN_INDEX only) — live-artifact root cause: the two flagged FACTS expressions (`ceiling` → `upper-interior-surface`, `windowless-room` → `space-bounded-by-walls-ceiling-floor`) exist ONLY in answers.md, never as `expr` lines in the extraction record, while every recorded expr WAS persisted (`index_absent_count=0`) — answer-time GLOSSES, paraphrases of recorded facts composed in new words while writing the final answer, not a record-vs-persist gap. Prompt-side fix, grading unchanged (the gate already checks FACTS against the record): step 1 binds BOTH query and FACTS lines to the record's exact spellings ("query AND answer vocabulary"); step 5 requires the FACTS: line be a VERBATIM COPY of recorded `expr` lines (copy before write, either persist-first-or-omit resolution); the format-block gate rules explain the false-claim semantics and place plain-language phrasing in the FINAL ANSWER text only. 181 offline unit tests (4 new v12 prompt tests in `unit/test_v12_prompt.py`).
- v13 (A_SKY lexical-blocker negation): 2026-10-26 19:04 UTC directive prep ("run all the other cases"; wr3l close-out) — the wr3l uncertainty case delivered a substantively correct honest answer and failed on `A_SKY` only: a grader-side false positive replicated on the answer text ("blocks any view of the sky" scored unnegated because "blocks" was missing from the negation lexicon). The lexicon gains lexical blockers (blocks/prevents/excludes/hides/obscures + inflections) under the same precede-the-claim window rule; an UNNEGATED claim still fails and a trailing blocker cannot rescue it. 188 offline unit tests (7 new v13 tests in `unit/test_v13_gates.py`).
- v16 (single-prompt TRUE/FALSE judge): 2026-10-26 22:56 UTC directive follow-up — the judge is ONE simple prompt: test question + the Omega agent's final answer + the expected correct answer, one OpenAI-compatible chat-completions request, reply TRUE/FALSE parsed as the blocking A-gate; endpoint configurable, defaults reuse the Omega agent's ASI:One asi1-ultra and API key; preflight smoke-checks the judge. 198 offline unit tests.
- v15 (case-set simplification + A-gate LLM judge): 2026-10-26 22:56 UTC directive — the case set is now `original`, `unsolvable`, `false` (removed `uncertainty`, `true`, `easy`, `difficult` + their prompt files; gates and the e2e procedure otherwise NOT relaxed), and answer-substance grading is ONE OpenAI chat-completions-compatible call (`llm_judge.py`: default ASI:One `https://api.asi1.ai/v1` model `asi1-ultra`, temperature 0, CORRECT/INCORRECT verdict; payload = question + ground truth + FINAL ANSWER line only — no reasoning/receipts/citations; key resolves arg > env > Omega `runtime.env`, never logged). `A_SKY`/`A_FABRICATED`/`A_NO_INABILITY` removed; `A_JUDGE_UNAVAILABLE` added (judge failure = blocking). judge tests in `unit/test_v15_judge.py`; obsolete v13 A_SKY lexicon tests removed).
- v14 (full-provenance extraction records): 2026-10-26 22:52 UTC directive ("save also the urls, git hash, etc. — whatever is necessary to reconstruct the provenance"; wr3m close-out) — the record's `source` line previously captured only `<filename> git:<sha>`, so at answer time the agent rebuilt SOURCES sha/url pairs from memory across wake cycles (the archive receipt does not survive wakes): that gap produced wr3i's one-position sha/url pair shift, wr3m true/difficult's corrupted sha transcription (one hand-retyped hex digit → `P_UNRESOLVED:COMMIT_NOT_IN_REPO`), and wr3m easy's fabricated URL on a valid sha (`P_UNRESOLVED:URL_MISMATCH`). Prompt-side fix, gates unchanged: step 1 appends the FULL provenance line per archive (`source <filename> git:<sha> sha256:<blob> path=<repo path> <raw-github-url>`, copied verbatim from the ARCHIVE-OK receipt); the record is now the "query, answer AND SOURCES vocabulary"; step 5 extends the v12 copy-not-compose rule to SOURCES (pairs copied character-for-character from recorded `source` lines — never re-typed, never re-paired, never guessed); format-block gate rules name the record's `source` lines as the only legitimate origin of citation pairs. 193 offline unit tests (5 new v14 prompt tests in `unit/test_v14_prompt.py`; 2 pre-existing wording pins updated to the v14 contract: v10's citation-pair pin, v12's vocabulary-binding pin).
- oc2 (OpenClaw-native shared-KB harness): 2026-11-04 22:54/22:58 UTC directive — the owner ABANDONS comparability with the Omega series and refocuses on the original objective (extract once, reason per case, strict provenance). The oc1 10-run failure analysis drove every change: (C1) the `pin` skill is DELETED (OpenClaw sessions retain conversation context across wake cycles; the pinned ledger was dead weight — the facts index / checkpoint manifest / answers.md are the durable working memory; the pin-derived `ADHERENCE_FALSE_COMPLETION` condition is removed with the channel, only the answers-file `ADHERENCE_DUPLICATE_BLOCK` check remains); (C3) `full` becomes the shared-KB flow — ONE run-level extraction (all 3 case questions as context, manifest poll, extraction log snapshot) then per-case reasoning; grade.json/report gain the shared-extraction section (manifest, receipts count, elapsed); (C4) stale-manifest archive moved to `results/<run-id>/archive-manifests/` OUTSIDE the agent-readable `knowledge-checkpoints/` (oc1a idle-trap); (C5) the stall-watchdog fresh-receipt signal reads the receipts SIDECAR lane in addition to the agent-container docker-log grep (oc1e false-abort: receipts flowed sidecar-only); (C6) per-phase session ids `wr-<run>-extract` / `wr-<run>-case-<case>` isolate phases from gateway restart-recovery zombies; (C7) prompt templates tightened and SHORTER than oc1 (word counts pinned by unit test). 475 offline unit tests.
- oc3 (reasoning battery): spec `specs/oc3-reasoning-battery/spec.md` — `full --battery battery` runs the 5 additional reasoning cases (the "manual reasoning questions": `stars-claim`, `floor-lamp`, `burned-bulb`, `stv-derivation`, `color-probe`) against the ALREADY-EXTRACTED live KB in DAS — no shared extraction, no cleanup-das (the live KB is reused and preserved); the preflight probes the read-proxy for a windowless-room fact and aborts when the KB is absent. `_case_by_id` resolves battery ids through `BATTERY_CASES` (facts.py, appended strictly after `TEST_CASES`); the per-case flow is identical to the standard reasoning flow (setup-reasoning-case → agent-case → grade-case); fresh `answers.md` per battery run, `facts-index.md` carries over; `gate_verdict` PASS iff all 5 cases PASS. 492 offline unit tests (17 new battery tests in `unit/test_oc3_battery.py`).

## OpenClaw-SUT adapter (agent profile `openclaw`)

The harness parameterizes the agent under test through an explicit
`--agent-profile` seam (spec:
[`specs/openclaw-sut-adapter/spec.md`](../../specs/openclaw-sut-adapter/spec.md);
oc2 changes: [`specs/oc2-openclaw-native/spec.md`](../../specs/oc2-openclaw-native/spec.md)).
The default `omega` profile keeps today's behavior byte-for-byte (the
control arm of the comparison); the `openclaw` profile points the same
harness at the OpenClaw-SUT gateway. The DAS-side containers
and the `omega-das-integration-client` network are shared by both arms.

```bash
python3 run_benchmark.py --agent-profile openclaw preflight --run-id <run-id>
python3 run_benchmark.py --agent-profile openclaw full --run-id <run-id>
```

- **Profile flag:** `--agent-profile omega|openclaw` (default `omega`).
  `--memory-volume` defaults to the profile's volume —
  `/var/lib/docker/volumes/openclaw-sut-workspace/_data` for openclaw.
- **oc2 run flow (`full`, shared-KB):** preflight → cleanup-das → ONE
  run-level EXTRACTION phase (the corpus is extracted ONCE per run; the
  prompt lists ALL THREE case questions as extraction context, never
  per-case framing) → checkpoint-manifest poll + extraction-container
  log snapshot (`results/<run-id>/windows/extract/phase1-docker.log`) →
  PER CASE (`original`, `unsolvable`, `false`): reasoning-phase restart
  → answer wait → grade → report (with the shared-extraction section:
  manifest, receipts count, elapsed) → teardown. `--cases` limits the
  REASONING cases (iteration mode); the shared extraction always covers
  all three. On extraction manifest-poll timeout WITHOUT a manifest the
  per-case reasoning still runs — each case is graded truthfully on the
  current state, the boundary is never invented. `--two-phase` is a
  deprecated no-op alias (the shared-KB flow IS two-phase and is the
  default `full` path).
- **Prompt delivery:** the harness writes the rendered `prompt.txt` into
  the workspace volume exactly as for Omega (setup-case, per-run backup,
  standby restore unchanged) and then starts a REAL agent turn with a
  PER-PHASE session id (oc2 C6): `wr-<run_id>-extract` for the shared
  extraction turn, `wr-<run_id>-case-<case_id>` for each per-case
  reasoning turn — `docker exec openclaw-sut-gateway openclaw agent
  --message-file /var/openclaw/workspace/prompt.txt --session-id
  <session-id> --no-color` — non-blocking; a nonzero-exit turn or a
  stall re-issues the same delivery (the frozen prompt is idempotent
  for wake cycles), bounded by the existing stall/phase-timeout
  machinery. Distinct sessions per phase keep gateway
  restart-recovery from re-dispatching a stale phase's zombie into the
  live phase's session.
- **Stale-manifest hygiene (oc2 C4):** before the run-level extraction
  installs its prompt, pre-existing checkpoint manifests are archived
  to `results/<run-id>/archive-manifests/` (harness-side, OUTSIDE the
  agent-readable `knowledge-checkpoints/` — the oc1a idle-trap: an
  in-volume archive let the agent find the archived manifest and follow
  the STOP rule) and the originals removed.
- **Receipts census (E-gate evidence):** docker logs stay the PRIMARY
  source (same `BRIDGE-PERSIST-OK: verified=<n> top=<handle>` regex,
  same `LLMRequest[` exclusion) and are UNIONED with a receipts sidecar
  the das-write skill appends to (`benchmark/persist-receipts.log`, one
  ISO-8601-prefixed receipt line per write) — windowed by the same
  since/until semantics, deduped on identical `(timestamp, handle)`
  pairs. Rationale: OpenClaw tool stdout is not guaranteed to reach
  docker logs; the sidecar makes the census robust without touching gate
  code.
- **Stall-watchdog forward signal (oc2 C5):** the fresh-persist-receipt
  signal reads BOTH lanes — the agent-container docker logs FIRST, then
  the receipts sidecar (same window semantics as the census union). The
  oc1e false-abort class (receipts flowed in the sidecar while the
  docker-log grep stayed silent → healthy extraction judged stalled) is
  eliminated; omega keeps the exact historical docker-only signal.
- **Restart semantics:** `sudo systemctl restart openclaw-sut.service`
  (the unit recreates the container: stop = `docker compose down`,
  start = `up -d`); `prompt.txt` is the openclaw profile's state file
  (standby/backup/restore parity with omega_state.md).
- **Preflight assertions (openclaw profile):** gateway container running
  on `omega-das-integration-client` with a reachable IP, workspace
  volume present, `benchmark/` artifact files creatable, write-bridge +
  read-proxy reachable FROM the SUT container, the six benchmark skills
  present in the workspace, and the Omega agent container ABSENT/STOPPED
  (the ASI1 key quota is shared).
- **`--dry-run`** prints the profile-resolved plan — including the exact
  agent-turn command — without touching docker.
- **Comparison note vs the Omega arm:** identical gates and identical
  history.metta snapshot/trim/window discipline. oc2 diverges from the
  Omega per-case series BY DIRECTIVE (the owner abandoned comparability
  to focus on the original objective — a reasoning agent with strict
  provenance tracking): the extraction runs ONCE per run (shared KB
  for all three cases), each reasoning turn is a distinct session, the
  pin skill is gone (OpenClaw sessions retain conversation context
  across wake cycles; the facts index / checkpoint manifest /
  answers.md artifacts are the durable working memory), and the prompt
  templates are shorter than the oc1 versions. Differences are
  mechanical only: agent container/volume/restart unit, the agent-turn
  delivery (vs Omega's restart-reads-prompt.txt), and the
  receipts-sidecar census union. Deployment of the SUT itself is
  `deploy/openclaw-sut/deploy.sh` (README there covers the env files and
  the smoke gates).
