# Plan — OpenClaw-SUT adapter (branch `openclaw-sut-adapter` off 180be65)

Phases are worker-owned unless marked [orchestrator].

## P1 — Harness profile seam (R-A1…R-A6, R-T1, R-T2)
Read run_benchmark.py end-to-end; introduce `--agent-profile` (default `omega`)
with a profile table at the top near the existing constants; route every
hard-coded agent reference through it; add openclaw delivery + receipts-sidecar
census + preflight checks; keep `omega` behavior identical. Unit tests first for
profile resolution and census fixtures, then implementation.

## P2 — Skills port (R-S1…R-S8)
Port in this order (contracts build on each other): das-write (receipt + sidecar),
das-retrieve (query grammar), metta (runtime wrapper, ephemeral atomspace, vendored
libs path — placeholders until orchestrator lands the libs), pin, then the two
composite procedure skills (das-extract-knowledge, das-grounded-reasoning). SKILL.md
descriptions de-Omega'd mechanically only (env var names, no benchmark vocabulary —
copy the Omega plugin descriptions' normative content).

## P3 — Deployment script + assets (R-D1…R-D8)
deploy.sh with the 10 ordered stages, Dockerfile.sut, compose, systemd unit,
config overlay, workspace seed, README. Secrets: env files supplied by the
orchestrator; scripts abort on missing/empty values and never print them.

## P4 — Docs + gate proof (R-X1…R-X3)
Harness README openclaw section, repo README realignment, frozen-file diff proof,
full unit suite run.

## Open design decisions (settled in spec; recorded here for the worker)
- Prompt delivery = gateway-backed `openclaw agent` turn per case, session-id
  `wr-<run_id>-<case_id>`, same prompt.txt content as the file the harness writes
  (backup/standby parity kept). NOT a Telegram send, NOT agent-exec: the Telegram
  channel exists for operator oversight only; the CLI turn is deterministic,
  scriptable, and session-scoped per case like Omega's fresh container.
- Receipt census = docker logs ∪ `benchmark/persist-receipts.log` sidecar
  (openclaw profile only); regex/payload identical; ISO-8601 prefix on sidecar
  lines for since/until windowing.
- `omega_state.md` analogue for openclaw = the prompt.txt itself (standby
  backup/restore parity), since OpenClaw has no equivalent single state file.
- MeTTa libs (`lib_pln.metta`, `lib_nal.metta`) are vendored files committed by
  the orchestrator [orchestrator, before deploy]; worker creates
  `deploy/openclaw-sut/metta-libs/README.md` placeholder explaining the
  provenance (extract verbatim from omegaclaw:v0.1.23-6376e99) and the Dockerfile
  COPYies whatever lands there.

## Orchestrator follow-ups (after worker acceptance; not worker tasks)
- Extract lib_pln.metta/lib_nal.metta from the Omega image on OVH, commit.
- Provision secretRefs into env files on OVH; run deploy.sh; smoke run; series.
