# OpenClaw ↔ DAS Bridge (with the Omega–DAS bridge history)

**Canonical tasks:** `openclaw-das-bridge` (active) · `omega-das-bridge` (historical control arm)
**Status:** ACTIVE — OpenClaw-SUT adapter campaign started 2026-11-03 (Balázs directive)
**Live progress doc (main reporting interface):** [Omega-DAS Integration Re-evaluation — Full Campaign Report](https://docs.google.com/document/d/1Pw5diOmac40Abc8_D1CG0_b3OrOHntq1BSzOv2H63dM/edit) — updated every iteration
**Live status page in this repo:** [`docs/status.md`](docs/status.md)

This repository is the **bridge repo between autonomous agents and the Distributed AtomSpace (DAS)**: a **standalone, config-only** deployment + automation layer that lets an agent persist knowledge **directly into DAS**, aligned with the intended Hyperon/OpenCog/SingularityNET architecture (agents write to DAS).

It now carries **two agent arms**, both bridge-only (no upstream code is forked or patched; every agent-facing capability is mounted/config at runtime):

1. **OpenClaw ↔ DAS (current):** the `openclaw` agent as a second system-under-test.
   - [`skills-sut/`](skills-sut/) — six OpenClaw workspace skills (das-write, das-retrieve, metta, pin, das-extract-knowledge, das-grounded-reasoning): the Omega plugin contracts ported to standalone exec CLIs, with the NAL/PLN MeTTa runtime vendored into the SUT wrapper image.
   - [`deploy/openclaw-sut/`](deploy/openclaw-sut/) — the pinned-image deployment (`deploy.sh`: build, seed, onboard, provider-verify, DAS-lane, smoke) for the OpenClaw-SUT gateway.
   - [`tests/reasoning-windowless-room/`](tests/reasoning-windowless-room/) — the e2e windowless-room gating benchmark, parameterized by `--agent-profile omega|openclaw` (identical frozen gates and prompts for both arms; see the README there).
   - Spec: [`specs/openclaw-sut-adapter/`](specs/openclaw-sut-adapter/).

2. **Omega ↔ DAS (historical, still the control arm):** the original campaign below. The Omega deployment, plugins, and campaign history stay under [`deploy/omega/`](deploy/omega/), [`docs/`](docs/), and [`historical/`](historical/), untouched.

**Agent-image provenance note (truth-corrected 2026-10-20, iteration 31):** the deployed agent image is a **fork build of upstream Omega** — `omegaclaw:das-f38217f` = [`ktfh-claw/OmegaClaw-Core`](https://github.com/ktfh-claw/OmegaClaw-Core) @ `f38217f`, based on upstream `singnet/Omega` v0.1.20 + PR #358. Upstream **publishes no container image** (verified 2026-10-20: no `ghcr.io/singnet/omega`, no `trueagi/omega` manifests; upstream CI builds without pushing), so the image is built from source. The fork deltas are enumerated in [`docs/architecture.md §Agent-image provenance`](docs/architecture.md). **Everything this bridge repo contributes is mounted at runtime** (plugins, overlays, prompts, adapter files) — nothing in the image is bridge-owned except the enumerated pre-campaign agent-infrastructure deltas (ASI:One provider, Telegram autonomous-wake line, ARC lane, the original das-retrieve adapter — now superseded at runtime by the mounted `das-read` plugin/v2 adapter). The DAS plane is 100% stock upstream pinned-digest images. **The OpenClaw-SUT arm consumes the upstream `openclaw/openclaw` image as a pinned tag** (digest-verified at deploy) — no fork, no patch; the wrapper stage adds only the MeTTa runtime + vendored NAL/PLN libs.

It supersedes the earlier "operator-gated DAS import" design documented here before 2026-10-19. That model is retired: the write path is becoming agent-direct, with narrow, logged, read-back-verified writes through the upstream `atomdb-broker` service. The old documents are preserved under [`historical/`](historical/) for provenance.

---

## What this repo provides

1. **DAS deployment automation** — everything needed to stand up the DAS stack + broker + read proxy + bridge components from scratch on a private host (compose files, configs, scripts, runbook).
2. **`das-write` write skill** — MeTTa in → atoms → `AtomDBProxy.add_atoms` via the service bus → mandatory read-back verification → verified handles returned to the agent. Shipped twice: as the Omega plugin (`deploy/omega/plugins/das-write/`) and as the OpenClaw exec CLI (`skills-sut/das-write/`, with the receipts-sidecar census lane).
3. **Bounded read path** — read proxy with the MeTTa-query parameter workaround applied (config-level; consumed from upstream once the client typo fix lands upstream).
4. **Thin import wrapper** — bulk/history loads via the stock upstream parser + `db_loader` image, with segmentation, syntax gating, newline-escape fallback, and provenance decoration.
5. **`&persistent` interception hook** — the agent's existing persistence vocabulary becomes durable, verified DAS writes.
6. **OpenClaw-SUT deployment + skills** — `deploy/openclaw-sut/` (pinned-image wrapper, compose, systemd unit, config overlay, workspace seed, `deploy.sh`) + `skills-sut/` (the six benchmark skills).
7. **The windowless-room gating benchmark** — `tests/reasoning-windowless-room/`: the agent-under-test e2e harness with the `--agent-profile` seam (omega = historical control arm, openclaw = current arm).
8. **Upstream contribution lane** — evidence-backed issue drafts and fork-local PRs for every defect this campaign found in upstream code (canonical home: [`low-cost-omega-setup` → `docs/contributions/`](https://github.com/ktfh-claw/low-cost-omega-setup/tree/main/docs/contributions); formerly duplicated in this repo, consolidated there 2026-11-08).

## Document map

| Document | Purpose |
|---|---|
| [`specs/openclaw-sut-adapter/`](specs/openclaw-sut-adapter/) | SDD spec/plan/tasks for the OpenClaw-SUT adapter (profile seam, skills port, deployment). |
| [`deploy/openclaw-sut/README.md`](deploy/openclaw-sut/README.md) | OpenClaw-SUT deployment: prerequisites, env files, stages, verification gates, harness invocation. |
| [`tests/reasoning-windowless-room/README.md`](tests/reasoning-windowless-room/README.md) | The windowless-room gating benchmark (both agent profiles) + the v1–v17 campaign provenance. |
| [`docs/architecture.md`](docs/architecture.md) | Path B design: components, data flows, interface contracts, topology, security model. |
| [`docs/campaign-plan.md`](docs/campaign-plan.md) | The overall task: directive, phases, deliverables, acceptance criteria, tracking rules. |
| [`docs/status.md`](docs/status.md) | Live status: iteration log with evidence links. Updated every cron iteration. |
| [`low-cost-omega-setup` → `docs/contributions/`](https://github.com/ktfh-claw/low-cost-omega-setup/tree/main/docs/contributions) | Upstream contribution ladder + per-contribution status (issues/PRs on forks) — canonical home, consolidated 2026-11-08 (previously `docs/contributions/` here). |
| [`docs/runbook.md](docs/runbook.md) | From-scratch deployment runbook (target: any operator can rebuild the whole lane). |
| [`historical/`](historical/) | Pre-bridge campaign documents (superseded operator-gated import lane, uplift provenance, experiment reports). |

## Architecture summary

```text
Omega arm (historical control; omega-curiosity, PeTTa/Omega upstream fork image)
  ├─ read:  das-retrieve skill → read-proxy → query-engine → attention-broker → MongoDB/Redis
  └─ write: das-write skill (this repo) → service bus → atomdb-broker → MongoDB
                └─ mandatory read-back verification via the query path

OpenClaw arm (current; openclaw-sut-gateway, pinned upstream openclaw/openclaw image)
  ├─ read:  das-retrieve skill (skills-sut/, exec CLI) → read-proxy → query-engine → …
  ├─ write: das-write skill (skills-sut/, exec CLI) → write-bridge facade → MongoDB
  │           └─ verified receipts: docker logs ∪ benchmark/persist-receipts.log sidecar
  ├─ metta: metta skill (skills-sut/) → vendored hyperon + lib_nal/lib_pln (ephemeral atomspace)
  └─ delivery: docker exec … openclaw agent --message-file prompt.txt --session-id wr-<run>-<case>

Shared DAS plane (stock upstream images, omega-das-integration-client network):
  write-bridge / read-proxy / query-engine / mongodb — untouched by this repo
```

Full design, contracts, and the three live-discovered deployment invariants: [`docs/architecture.md`](docs/architecture.md).

## Security model (short form)

- No DAS ports published to the host; all traffic stays on internal Docker networks.
- Writes are narrow (single skill), logged (handle + content), and revocable (handles → delete).
- Write claims are only credible with broker evidence **plus** independent read-back verification.
- No database credentials inside the agent container; the agent talks to the bus, not the DB.

## Rules of engagement (standing, from the directive)

- All work stays on the `ktfh-claw` forks and this repo's `main` branch; **nothing upstream without explicit approval**.
- New code → pushed to the fork repos, with GitHub links recorded in the live Google Doc.
- Upstream issue/PR content is drafted and, where executable, opened **only in the forked repositories** first.
- Outdated fork branches are archived/deleted as they are superseded (see the contributions ladder in [`low-cost-omega-setup`](https://github.com/ktfh-claw/low-cost-omega-setup/tree/main/docs/contributions)).
- The Google Doc is the main reporting interface; `docs/status.md` mirrors it per iteration.
