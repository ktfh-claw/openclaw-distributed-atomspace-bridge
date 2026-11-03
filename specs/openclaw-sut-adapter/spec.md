# SDD Spec — OpenClaw-SUT adapter: e2e windowless-room benchmark on OpenClaw

Directive: Balázs, 2026-11-03 11:30 UTC (Discord DM). Branch:
`openclaw-sut-adapter` off origin/main @180be65 (frozen sks2 harness commit).
Primary input: `specs/openclaw-sut-adapter/` (this spec) + the S1 seam assessment
at `memory/openclaw-das-bridge-campaign/s1-adapter-seam-assessment.md`
(orchestrator-side path; its content is restated here where normative).

## Goal

Run the existing e2e windowless-room reasoning benchmark with **OpenClaw** as the
agent under test ("OpenClaw-SUT"), as a **bridge-only** adaptation, so a 10-run
OpenClaw series can be compared against Omega's sks2 skill-split series.

## Hard invariants (violations = reject the diff)

1. **Frozen gate files stay byte-identical** vs the branch base (180be65):
   `tests/reasoning-windowless-room/grading.py`, `facts.py`, `history_parse.py`,
   `llm_judge.py`, `provenance_check.py`, everything under
   `tests/reasoning-windowless-room/prompts/`, `background/`, and the three
   `agent_*_prompt_template.md` files, plus the reference
   `expected-answer.md`/`original-prompt.md`/`false-statement-prompt.md`/
   `unsolvable-unrelated-prompt.md`. Check with
   `git diff 180be65 -- <paths>` (must be empty).
2. **`run_benchmark.py` keeps its existing Omega behavior as the default.**
   All adaptation goes through an explicit agent-profile seam (below). With no
   profile flag (or `--agent-profile omega`), the rendered commands, container
   names, paths, restart semantics, and receipt-census sources must be
   byte-for-byte the same behavior as today. Omega is the control arm of the
   comparison; a regression there invalidates the campaign.
3. **No upstream modifications.** Do not fork/patch OpenClaw, PeTTa, or DAS
   code. The OpenClaw image is consumed as a pinned tag; everything else is
   added by files in THIS repo (skills, wrapper image stage, compose, scripts).
4. **DAS deployment untouched.** The write bridge / read proxy / query engine /
   mongodb compose services are addressed over the existing
   `omega-das-integration-client` docker network at their existing origins.
   Nothing in this repo may modify those services or their configs.
5. **Secrets never in the repo, logs, or stdout.** Deploy-time credentials are
   passed via environment / env files produced outside the repo by the
   orchestrator. Scripts must not `set -x`, must not `echo`/`env`/`cat` secret
   values, and committed examples must contain placeholders only.
6. **Only benchmark-necessary tools enabled for the SUT** (directive): the
   OpenClaw-SUT config enables file + exec tools and the six benchmark skills;
   websearch/browser/messaging/channel tooling beyond the Telegram chat channel
   must be off. The frozen prompt itself forbids websearch; config must too.

## The seam the harness must parameterize

Today `tests/reasoning-windowless-room/run_benchmark.py` hard-codes (constants
at lines ~80–110): `DEFAULT_MEMORY_VOLUME`, `CONTAINER_AGENT = "omega-curiosity"`,
`CONTAINER_WRITE_BRIDGE/READ_PROXY/QUERY_ENGINE/MONGODB`, `BENCH_PROMPT_REL =
"repos/Omega/memory/benchmark"` (+ answers/facts/urls relatives), and restarts
via `sudo systemctl restart omega-curiosity.service`.

### Agent profile (new `--agent-profile` argument, default `omega`)

Introduce a small, typed profile dataclass/dict in run_benchmark.py, e.g.:

```
omega (default, behavior identical to today):
  container_agent        omega-curiosity
  memory_volume_default  /var/lib/docker/volumes/omega-curiosity-memory/_data
  bench_prompt_rel       repos/Omega/memory/benchmark (+answers/facts/urls)
  state_file             omega_state.md            (backup/restore as today)
  restart                ["sudo","systemctl","restart","omega-curiosity.service"]
  prompt_delivery        restart_only              (prompt.txt read at start)
  receipts_source        docker_logs               (exactly today's census)
  das origins            defaults as today
openclaw:
  container_agent        openclaw-sut-gateway
  memory_volume_default  /var/lib/docker/volumes/openclaw-sut-workspace/_data
  bench_prompt_rel       benchmark (+answers.md/facts-index.md/urls.txt)
  state_file             prompt.txt                (standby/backup/restore parity)
  restart                ["sudo","systemctl","restart","openclaw-sut.service"]
  prompt_delivery        file_plus_agent_turn      (see below)
  receipts_source        docker_logs_and_receipts_file (see below)
  das origins            same discovery (unchanged _container_ip path)
```

The DAS-side container constants (write bridge / read proxy / query engine /
mongodb) and the `omega-das-integration-client` network are shared by both
profiles and stay as they are.

Requirements:

- **R-A1** Every place that currently reads the hard-coded agent constants must
  resolve through the profile. Grep targets: `CONTAINER_AGENT`, `BENCH_PROMPT_REL`
  and the three derived prompt-relative paths, `DEFAULT_MEMORY_VOLUME`,
  `omega-curiosity.service`, `omega_state.md`, `prompt.txt` handling, and the
  `_docker_logs_since` agent calls.
- **R-A2** Prompt delivery (`openclaw` profile): the harness writes the rendered
  `prompt.txt` into the memory volume exactly as today (setup-case, per-run
  backup, standby restore — unchanged), AND then starts a real agent turn,
  non-blocking with a bounded timeout, inside the SUT gateway container:
  `docker exec <container_agent> openclaw agent --message-file <abs-in-container
  prompt.txt path> --session-id wr-<run_id>-<case_id> --no-color`
  (final flags verified against the pinned image at smoke; the seam function
  must make the command list a single testable unit). If the turn process exits
  nonzero or the answer block is still absent when the existing stall watchdog
  fires, re-issue the same delivery (the frozen prompt is idempotent for wake
  cycles by design); re-issue counts and bounds reuse the existing
  stall/phase-timeout machinery, not new policy.
- **R-A3** Receipt census (`openclaw` profile): keep docker-logs census as the
  primary source (same `BRIDGE-PERSIST-OK: verified=\d+ top=[0-9a-f]{32}` regex,
  same `LLMRequest[` exclusion), and union it with a receipts sidecar file the
  das-write skill appends to (`<memory-volume>/benchmark/persist-receipts.log`,
  one line per receipt: `<ISO8601-UTC> BRIDGE-PERSIST-OK: verified=N top=H`,
  timestamp-parsed for the same since/until window semantics). Dedup identical
  (timestamp,handle) pairs. Rationale: OpenClaw tool stdout is not guaranteed to
  reach `docker logs`; the sidecar makes the census robust without touching gate
  code. The receipts regex/payload stays identical in both sources.
- **R-A4** `history.metta` handling is identical for both profiles: same
  snapshot pre/post, same trim marker, same window logic. The openclaw profile's
  memory volume simply hosts `history.metta` at its root (the SUT skills own
  writing it; see skills contract below).
- **R-A5** Preflight assertions for the openclaw profile: gateway container
  running on `omega-das-integration-client` with a reachable IP
  (reuse `_pick_agent_ip`), workspace volume present, `benchmark/` artifact
  files creatable, write-bridge + read-proxy reachable from the SUT container
  (same `_container_ip` discovery), and the Omega agent container ABSENT/STOPPED
  on the host (`docker ps` filter for `omega-curiosity` must be empty) because
  the ASI1 key quota is shared.
- **R-A6** Dry-run support: `--dry-run` must print the profile-resolved
  plan (including the exact agent-turn command) without executing it, same as
  the omega profile does today.

## OpenClaw-SUT deployment (script-first, directive 7)

New directory `deploy/openclaw-sut/` containing:

- **R-D1 `deploy.sh`** — the single e2e entry point. Ordered, fail-fast stages,
  each idempotent and `set -euo pipefail` safe:
  1. preflight: docker + compose v2 present, `omega-curiosity` container not
     running (abort with a clear message otherwise), DAS compose network
     `omega-das-integration-client` exists, required env files present;
  2. build SUT wrapper image `openclaw-sut:2026.10.10-metta1` from
     `Dockerfile.sut` (pinned base `openclaw/openclaw:2026.10.10`,
     index digest `sha256:1e5ee6c7d02d5b5f64f9cf26a30c7ef7d4ec292f0d25fa590f4b7e103e8bf799`
     verified at pull);
  3. create the `openclaw-sut-workspace` named volume and seed it
     (workspace-seed below) if not already seeded;
  4. write the runtime env file from the orchestrator-provided secret env
     files (never echo values; abort if a required var is empty);
  5. onboard the gateway non-interactively headless-style: token auth via
     `OPENCLAW_GATEWAY_TOKEN` env, provider = OpenAI-compatible ASI1
     (`OPENAI_API_KEY` value = ASI1 key, base URL `https://api.asi1.ai/v1`,
     model `asi1-ultra`), `--skip-channels`, `--no-install-daemon`;
     then set the benchmark config overlay (see R-D3);
  6. add the Telegram channel via `channels add --channel telegram --use-env`
     (token from `TELEGRAM_BOT_TOKEN` env only);
  7. `docker compose up -d`; connect the gateway container to
     `omega-das-integration-client`;
  8. verify the provider with a REAL minimal API call through the SUT config
     (one-token completion against `https://api.asi1.ai/v1`); abort on auth
     failure with "re-request the OPENCLAW_SUT_ASI1_API_KEY secret" wording;
  9. verify the DAS lanes from inside the SUT container (TCP reach of write
     bridge + read proxy IPs on the client network);
  10. smoke: `docker exec` a `metta` runtime check (`(|- ...)` operator
      evaluates) and a skill-visibility check (`openclaw skills list`-equivalent
      shows the six benchmark skills), print a deployment report (no secrets).
- **R-D2 `Dockerfile.sut`** — wrapper stage on the pinned base tag. Installs the
  MeTTa runtime (hyperon via pip, plus python3 if the base lacks it) and vendored
  `lib_pln.metta` + `lib_nal.metta` under `/opt/sut-metta/`. No other mutation
  of the base image. (Orchestrator commits the two vendored lib files —
  extracted verbatim from `omegaclaw:v0.1.23-6376e99` — before deploy; see
  tasks.md split. The Dockerfile just COPYies them.)
- **R-D3 `sut-config-overlay.json`** (or equivalent `config set --batch-json`
  payload file) — benchmark-necessary config only:
  - provider: OpenAI-compatible ASI1, base URL `https://api.asi1.ai/v1`,
    model `asi1-ultra`;
  - tools: enable file (read/write/edit/ls/apply_patch) + exec only; deny
    websearch, browser, messaging/sends, plugins marketplaces;
  - skills: workspace `skills/` directory enabled for the six benchmark skills;
  - workspace root: in-container path `/var/openclaw/workspace`
    (mounted from `openclaw-sut-workspace`);
  - autonomous/scheduled features OFF (no cron, no heartbeats) — turns happen
    only when the harness delivers them;
  - log level: keep skill-script stdout visible in container logs (verify at
    smoke; the receipts sidecar removes the hard dependency).
- **R-D4 `docker-compose.yml`** — gateway service from `openclaw-sut:2026.10.10-metta1`,
  container_name `openclaw-sut-gateway`, named volume → `/var/openclaw/workspace`,
  env_file runtime.env, no published ports beyond localhost gateway port
  (Control UI/token stays local), `restart: unless-stopped`. CLI service per the
  official image pattern if needed by `compose run`.
- **R-D5 `openclaw-sut.service`** — systemd unit mirroring the Omega start.sh
  semantics for the harness restart path: stop = `docker compose down`
  (removes containers), start = `docker compose up -d` (fresh containers), so
  `systemctl restart openclaw-sut.service` recreates rather than reuses.
- **R-D6 `runtime.env.example`** — placeholder-only (OPENAI_API_KEY=,
  TELEGRAM_BOT_TOKEN=, OPENCLAW_GATEWAY_TOKEN=, OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN=,
  OPENCLAW_SUT_READ_PROXY_ORIGIN=, OPENCLAW_STATE_DIR=…).
- **R-D7 `workspace-seed/`** — seeded into the volume root:
  `AGENTS.md` (minimal standing instruction: you are an agent under a machine
  graded benchmark; the case prompt's task list is authoritative and must be
  followed exactly; artifact paths are workspace-relative; history.metta is
  your working-memory ledger — no extra hints, no benchmark answers),
  `benchmark/` scaffold (`answers.md`, `facts-index.md`, `urls.txt`,
  `pinned-ledger.md`, `knowledge-checkpoints/` as empty/seeded files),
  `skills/` (the six skills, R-S below), standby `prompt.txt`
  (matches the Omega standby content pattern), empty `history.metta`.
- **R-D8 `README.md`** in `deploy/openclaw-sut/` — what/why, host prerequisites,
  the env files the orchestrator supplies, stage list, verification gates, and
  the exact harness invocation for the openclaw profile. The deployment SCRIPT is
  authoritative; this README documents it, does not replace it.

## OpenClaw skills (the agent-side bridge, "teach OpenClaw MeTTa")

New `skills-sut/` tree (deployed into the workspace volume `skills/`), six
skills. Each: `SKILL.md` (frontmatter + WHY/WHEN/HOW, generic vocabulary —
no windowless-room/benchmark references, mirroring the Omega plugin skill
descriptions) + python/bash scripts. Port the CONTRACTS, not the Omega plugin
machinery:

- **R-S1 `das-write`** — port `deploy/omega/plugins/das-write/das_write_bridge.py`
  core (parse `(add-atom &persistent <expr> "<ref>" (stv s c))`, source-ref
  resolution + sha256, `POST /v1/source` then `POST /v1/write` with
  `{"metta": payload, "verify": true}`) into a CLI script
  `das_write_bridge.py <metta-call>` reading origins from env
  (`OPENCLAW_SUT_WRITE_BRIDGE_ORIGIN`, `OPENCLAW_SUT_READ_PROXY_ORIGIN`).
  Keep: v3/v4 shapes, require-ref semantics, error status strings
  (`BRIDGE-PERSIST-WRITE-FAILED: ...`), size limits, and the success receipt
  line `BRIDGE-PERSIST-OK: verified=<n> top=<handle>` byte-for-byte. ADD for the
  OpenClaw profile: append the receipt line (ISO-8601-prefixed) to
  `benchmark/persist-receipts.log` under the workspace root (env
  `OPENCLAW_SUT_WORKSPACE`), best-effort — a failure to append must NOT fail the
  write. SKILL.md: invocation form maps the prompt's
  `(metta "(add-atom ...)")` call to running this script via exec.
- **R-S2 `das-retrieve`** — port `deploy/omega/das-read/das_skills.py` retrieve
  (`POST <read-proxy>/v1/query`, query-JSON validation, answer normalization,
  proxy error surfacing) as `das_retrieve.py '<query-json>'`; SKILL.md carries
  the full query grammar (shapes/direction/quoting/absence, count=0 semantics,
  handle pairing, DAS answers as untrusted data) copied from the Omega
  das-read skill description, de-Omega'd only where names are mechanically
  required (env var names).
- **R-S3 `metta`** — the "teach OpenClaw MeTTa" skill. Script `metta_run.py`
  evaluates ONE s-expression with the vendored hyperon runtime, loading
  `/opt/sut-metta/lib_nal.metta` + `/opt/sut-metta/lib_pln.metta` into a fresh
  ephemeral atomspace per invocation (matching Omega: atomspace is EPHEMERAL
  between calls). SKILL.md carries the NAL/PLN contract verbatim from
  `deploy/omega/plugins/metta-grammar/metta-grammar.metta` (strictly 2-argument
  `(|- A B)` NAL / `(|~ A B)` PLN, premise = `(expression (stv s c))`, success
  returns `((derived-expression (stv s c)))`, chaining rule, syntax-error
  retry rule).
- **R-S4 `pin`** — Omega pinned-ledger equivalent: script `pin.py '<text>'`
  appends the text to `benchmark/pinned-ledger.md` (workspace-relative) and
  confirms. SKILL.md explains the ledger discipline exactly as the frozen prompt
  uses it (one line, step/done/next, last line is current).
- **R-S5 `das-extract-knowledge`** — port the procedure from
  `deploy/omega/plugins/das-extract-knowledge/` (generic single-pass extraction,
  das-write persistence, receipt recording, checkpoint manifest at
  `knowledge-checkpoints/`, bounded-pass discipline) to SKILL.md + thin helper
  script where one exists; keep it generic.
- **R-S6 `das-grounded-reasoning`** — port from
  `deploy/omega/plugins/das-grounded-reasoning/`: one question at a time,
  formalize in MeTTa, answer strictly from the DAS KB, grounding rules
  (recorded exprs verbatim, count=0 probing, truthful negatives, checkpoint
  manifest as entry point).
- **R-S7** Skills' file writes (facts-index, answers, history) use the paths
  the harness renders into the prompt via the existing template variables; the
  skills must treat those as authoritative arguments, never hard-code
  benchmark paths in prose beyond the workspace-relative convention.
- **R-S8 history.metta ownership**: the das-write / metta / das-retrieve scripts
  append an episode line (`; <iso> <op> <summary>` + the verbatim MeTTa call and
  result) to `history.metta` at the workspace root, best-effort (same as the
  Omega plugin path kept the ledger current). Trim discipline stays with the
  harness (R-A4).

## Harness docs + README

- **R-X1** `tests/reasoning-windowless-room/README.md`: add an OpenClaw-SUT
  section (profile flag, memory-volume default, delivery semantics, receipts
  sidecar, preflight assertions, comparison note vs Omega arm).
- **R-X2** Repo `README.md`: re-align to the repo's new purpose (OpenClaw ↔ DAS
  bridge + the Omega DAS bridge history). Historical Omega material stays under
  `deploy/omega/`, `docs/`, `historical/`, and `specs/` untouched.
- **R-X3** No file outside `deploy/openclaw-sut/`, `skills-sut/`,
  `tests/reasoning-windowless-room/README.md`, repo `README.md`, and
  `run_benchmark.py` may change (plus the new spec files themselves). In
  particular `deploy/omega/**` and `deploy/das/**` are frozen for this task.

## Tests (worker-owned, run before push)

- **R-T1** Unit tests (extend `tests/reasoning-windowless-room/unit/`, following
  the existing `run_tests.py` style, no network/docker needed):
  - profile defaults: omega profile resolves to today's exact constants;
  - openclaw profile resolves paths/commands per R-A1–R-A3;
  - receipts sidecar census: union + dedup + window filtering with fixture
    lines, including interleaved docker-log lines;
  - delivery command construction (exact argv, session-id format);
  - preflight command construction (assert-Omega-stopped check);
  - existing suite stays green (run the whole unit directory).
- **R-T2** `bash -n` + ShellCheck (if available in PATH, else note it) for
  `deploy.sh` and the systemd unit's ExecStart; `python3 -m py_compile` on all
  new python; `git diff 180be65 --stat` must show frozen paths empty.
- **R-T3** Deterministic dry-run: running the openclaw-profile preflight/dry-run
  code paths against stubbed subprocess output must not require docker.

## Ownership boundary

- **Worker (this task):** code + skills + tests + docs in the fork, push to
  `origin/openclaw-sut-adapter` only. NO deploys, NO remote hosts, NO docker
  builds against live hosts, NO secret values, NO channel creation.
- **Orchestrator (after acceptance):** extract + commit vendored MeTTa libs,
  provision the OVH deploy, materialize secretRefs, run the smoke and the series.

## Stop-and-ask conditions

Stop and report instead of working around if:
- the frozen-gate constraint conflicts with a needed harness change (it should
  not — any such need means the profile seam is designed wrong);
- the pinned OpenClaw image's CLI flags cannot support
  `openclaw agent --message-file ... --session-id ...` (do not invent flags;
  report the actual `--help` surface you based the design on);
- a skills contract cannot be honored without touching prompt/gate files.

## Report format (worker)

Commit SHAs (base..head), per-requirement status (R-A…/R-D…/R-S…/R-T…), test
command + full output summary, `git diff 180be65 --stat`, frozen-file diff
proof (empty), design decisions, deviations, blockers.
