# OpenClaw-SUT deployment (windowless-room benchmark arm)

Deploy **OpenClaw as the agent under test ("OpenClaw-SUT")** for the
windowless-room reasoning benchmark, as a bridge-only adaptation: the
pinned upstream image is consumed as-is (never forked or patched), and
everything else — the six benchmark skills, the wrapper image stage, the
compose stack, this script — lives in this repo. The DAS deployment
(write bridge / read proxy / query engine / mongodb) is untouched and is
addressed over the existing `omega-das-integration-client` docker network.

**The deployment SCRIPT is authoritative — this README documents it.**
Spec: `specs/openclaw-sut-adapter/spec.md` (R-D1..R-D8).

## What is deployed

| Piece                     | What                                                        |
| ------------------------- | ----------------------------------------------------------- |
| `openclaw-sut-gateway`    | gateway container from `openclaw-sut:2026.10.10-metta1`     |
| wrapper image             | pinned base `openclaw/openclaw:2026.10.10` + the upstream-pinned MeTTa runtime (SWI-Prolog 10.0.2 + PeTTa v1.0.4 + vendored NAL/PLN libs in `/opt/sut-metta/` — provenance below) — nothing else mutated |
| `openclaw-sut-workspace` | named volume → `/var/openclaw/workspace`: seeded scaffold (`workspace-seed/`) + the six skills (`<repo>/skills-sut/`) |
| `openclaw-sut-state`     | named volume → `/var/openclaw/state` (`OPENCLAW_STATE_DIR`): onboarded config + sessions — survives container recreation |
| DAS network              | gateway attached to `omega-das-integration-client` (write bridge + read proxy origins into the runtime env) |
| Telegram channel         | operator oversight only; token stays in the environment (`--use-env`) |
| systemd unit             | `openclaw-sut.service`: stop = `docker compose down`, start = `up -d` → `systemctl restart` RECREATES the container; ExecStartPost re-attaches the DAS network |

## Host prerequisites (orchestrator, on the OVH deploy host)

- docker + compose v2
- the DAS compose stack running (network `omega-das-integration-client`)
- the **Omega agent stopped** (`sudo systemctl stop omega-curiosity.service`)
  — the ASI1 key quota is shared; deploy.sh refuses to run while it is up
- the vendored `lib_nal.metta` + `lib_pln.metta` committed under
  `metta-libs/` (fetch from upstream singnet/Omega @ `b94f7bf44e10852e491967191f1c68643dc9ca90`
  and verify the sha256s — see `metta-libs/README.md`; stage 2 fails fast
  without them)
- the orchestrator **secrets env file** (outside this repo, never committed),
  shell `KEY=VALUE` lines:
  - `OPENCLAW_SUT_ASI1_API_KEY` — the ASI1 provider key
  - `OPENCLAW_SUT_TELEGRAM_BOT_TOKEN` — the Telegram bot token
  - `OPENCLAW_SUT_GATEWAY_TOKEN` — the OpenClaw Gateway auth token

  deploy.sh stage 4 derives the runtime env from it (`OPENAI_API_KEY`,
  `CUSTOM_API_KEY`, `TELEGRAM_BOT_TOKEN`, `OPENCLAW_GATEWAY_TOKEN`) +
  the discovered DAS origins, writes `runtime.env` (umask 077, gitignored),
  and aborts naming the missing variable — secret VALUES are never echoed,
  catted, or logged (no `set -x` anywhere).

## Running the deploy (single entry point)

```bash
cd deploy/openclaw-sut
./deploy.sh --secrets-file /path/to/orchestrator-secrets.env
```

## The 10 stages (ordered, fail-fast, individually idempotent)

1. **preflight** — docker + compose v2 present; `omega-curiosity` not
   running (clear abort message otherwise); DAS client network exists;
   the secrets env file exists and is non-empty; the deploy assets exist.
2. **build** — pull `openclaw/openclaw:2026.10.10`, verify its index digest
   is `sha256:1e5ee6c7d02d5b5f64f9cf26a30c7ef7d4ec292f0d25fa590f4b7e103e8bf799`,
   build `openclaw-sut:2026.10.10-metta1` from `Dockerfile.sut`.
3. **volume + seed** — create `openclaw-sut-workspace`, seed it once from
   `workspace-seed/` (AGENTS.md, standby `prompt.txt`, empty
   `history.metta`, `benchmark/` scaffold: answers.md, facts-index.md,
   urls.txt, knowledge-checkpoints/) plus the five skills
   from `<repo>/skills-sut/`; the `.sut-seeded` marker makes it idempotent
   (delete the marker — or the volume — to reseed). A stale
   `skills/pin` directory from a prior deployment is removed
   idempotently (the pin skill is retired, oc2-openclaw-native C1).
4. **runtime env** — write `runtime.env` from the orchestrator secrets
   (abort on empty values, names only) + the write-bridge/read-proxy IPs
   discovered on the DAS client network.
5. **onboard + overlay** — non-interactive headless onboarding via the
   official Docker pattern (`compose run --entrypoint node`): token auth
   via the `OPENCLAW_GATEWAY_TOKEN` env SecretRef, OpenAI-compatible
   custom provider = ASI1 (`CUSTOM_API_KEY` env ref,
   `https://api.asi1.ai/v1`, model `asi1-ultra`), `--skip-channels
   --no-install-daemon --skip-bootstrap` (the seeded AGENTS.md stays the
   only standing instruction). Then apply `sut-config-overlay.json` via
   `config patch --file`: workspace root `/var/openclaw/workspace`, tool
   policy minimal + file/exec only, explicit denies (web/browser/messaging/
   sends/plugins marketplaces), `cron.enabled=false` + `triggers.enabled=false`
   (turns happen only when the harness delivers them), plugins allowlist
   `["telegram"]`. Heartbeat off via `system heartbeat disable` (tolerant —
   cron config is the hard gate).
6. **telegram** — `channels add --channel telegram --use-env` (token from
   `TELEGRAM_BOT_TOKEN` env only; never copied into the config).
7. **up** — `docker compose up -d`; connect the gateway to
   `omega-das-integration-client` (skip if already attached).
8. **provider verify** — a REAL one-token completion against
   `https://api.asi1.ai/v1` using the exact provider credential the SUT
   turns use (`CUSTOM_API_KEY`, read from the container env inside the
   python process — never on a command line). HTTP 401/403 aborts with:
   *"re-request the OPENCLAW_SUT_ASI1_API_KEY secret"*.
9. **DAS lanes** — TCP reach of the write bridge + read proxy origins from
   inside the SUT container (same origins the skills use).
10. **smoke** — (a) metta runtime check: `(|- ...)` evaluates through the
    SUT metta skill with `(stv ...)` output (scratch workspace, so the
    smoke never touches the seeded ledger); (b) skill-visibility: the five
    benchmark skills (das-write, das-retrieve, metta,
    das-extract-knowledge, das-grounded-reasoning) appear in
    `skills list`; (c) a deployment report (no secrets).

## MeTTa runtime provenance (spec addendum — upstream-pinned, repeatable by anyone)

The wrapper image's MeTTa runtime is pulled ENTIRELY from upstream pins
(the same runtime the Omega arm uses, at the same versions); there is NO
dependency on any omega-built artifact:

| Piece            | Upstream                                                   | Pin                                            | How the build pulls it |
| ---------------- | ---------------------------------------------------------- | ---------------------------------------------- | --------------------- |
| SWI-Prolog       | https://hub.docker.com/_/swipl — official image             | `docker.io/library/swipl:10.0.2`               | `COPY --from=docker.io/library/swipl:10.0.2` (binary `/usr/bin/swipl`, home `/usr/lib/swipl`, plus the two shared libs the slim base lacks: `libtcmalloc_minimal.so.4`, `libpython3.11.so.1.0` — the exact DT_NEEDED delta) |
| PeTTa            | https://github.com/trueagi-io/PeTTa.git                     | v1.0.4 = commit `7037f4c2ad378c52fc328004fe216d5118b674f0` | build-stage `git clone` + `git checkout` of the pinned commit; only `src/*.pl` is kept (nothing from PeTTa's `build.sh` — no faiss/mork/chroma) |
| NAL/PLN libs     | https://github.com/singnet/Omega.git                        | commit `b94f7bf44e10852e491967191f1c68643dc9ca90` | vendored in-repo (`metta-libs/`, sha256-verified — repeat-fetch in `metta-libs/README.md`), `COPY` at build |

`skills-sut/metta/metta_run.py` invokes it exactly as the omegaclaw
runtime does: `swipl --stack_limit=8g -q -s src/main.pl -- <file>` with
`cwd=/opt/petta`, a fresh swipl process per call (ephemeral atomspace).
The build itself gates the runtime: a NAL probe must yield an `(stv ...)`
result line or the image build fails. The `omegaclaw:v0.1.23-6376e99`
container is used only as a CROSS-CHECK of these pins (comparability
proof in the spec addendum), never as a source.

## Verification gates

- Stage 2's digest check pins the base image byte-for-byte.
- Stage 8 proves the provider credentials work through the SUT's own
  env-ref path before any benchmark run.
- Stage 9 proves the DAS lanes are reachable from the SUT container.
- Stage 10 proves the MeTTa runtime + vendored libs work and the skills
  are visible — the exact capabilities the graded turns depend on.
- The harness adds its own preflight assertions (run_benchmark.py
  `--agent-profile openclaw preflight`): gateway on the DAS network with
  a reachable IP, workspace volume present, `benchmark/` artifacts
  creatable, both DAS lanes reachable from the SUT, and the Omega agent
  container ABSENT/STOPPED (shared key quota).

## Harness invocation (openclaw profile)

From `tests/reasoning-windowless-room/` on the host with this checkout:

```bash
python3 run_benchmark.py --agent-profile openclaw preflight --run-id <run-id>
python3 run_benchmark.py --agent-profile openclaw full --run-id <run-id>
```

- run flow (oc2, shared-KB): preflight → cleanup-das → ONE run-level
  extraction phase (all 3 case questions as context; the corpus is
  extracted ONCE per run) → checkpoint-manifest poll + extraction log
  snapshot → per-case reasoning turns → grade → report → teardown.
  `--two-phase` is a deprecated no-op alias (the shared-KB flow IS
  two-phase and is the default `full` path).
- prompt delivery: the harness writes the rendered `prompt.txt` into the
  workspace volume exactly as for Omega and then starts a real gateway
  turn with a PER-PHASE session id (oc2 C6): `wr-<run_id>-extract` for
  the shared extraction turn, `wr-<run_id>-case-<case_id>` for each
  per-case reasoning turn — `docker exec openclaw-sut-gateway openclaw
  agent --message-file /var/openclaw/workspace/prompt.txt --session-id
  <session-id> --no-color` (non-blocking; re-issued on nonzero exit or
  a stall via the existing stall/phase-timeout machinery; distinct
  sessions keep gateway restart-recovery from re-dispatching a stale
  phase's zombie into the live phase's session)
- receipts census: docker logs (primary) ∪
  `benchmark/persist-receipts.log` sidecar (ISO-8601 lines appended by the
  das-write skill), identical `(timestamp, handle)` dedup; the
  stall-watchdog fresh-receipt forward signal reads the same two lanes
  (oc2 C5 — receipts can flow sidecar-only while the docker-log grep
  stays silent)
- restarts: `sudo systemctl restart openclaw-sut.service` (recreates the
  container; the unit re-attaches the DAS network)
- `--dry-run` prints the full profile-resolved plan (including the exact
  delivery command) without touching docker.

## Smoke-time verifications (orchestrator, S4)

- the pinned image's `openclaw` binary is on the container PATH (the frozen
  delivery command uses `docker exec <container> openclaw agent ...`; if the
  image only exposes `node /app/dist/index.js`, report back — do not invent
  a different delivery)
- onboarding/config-patch flag surfaces against the pinned tag (this script
  follows the documented `2026.10.x` CLI surface: `onboard --non-interactive
  --accept-risk --skip-health --mode local --auth-choice custom-api-key
  --custom-base-url --custom-model-id --custom-compatibility openai
  --secret-input-mode ref --gateway-auth token --gateway-token-ref-env
  --skip-channels --no-install-daemon --skip-bootstrap`, `config patch
  --file`, `channels add --channel telegram --use-env`, `skills list`,
  `system heartbeat disable`)
- the seeded `AGENTS.md` is injected into turns (bootstrap skipped)
- skill-script stdout visible in `docker logs` (the receipts sidecar removes
  the hard dependency; the E-gate census is robust either way)
