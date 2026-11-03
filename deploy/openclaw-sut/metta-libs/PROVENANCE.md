# Vendored metta libs — provenance & verification (R-D2 prep)

Verified: 2026-11-03 13:32 UTC by orchestrator (cron tick).

## Source (authoritative)

Image: `omegaclaw:v0.1.23-6376e99` (running container `omega-curiosity` on OVH
omega-experimental, Tailscale 100.84.81.96:9022).

Source paths in image:
- `/PeTTa/repos/Omega/lib_nal.metta`
- `/PeTTa/repos/Omega/lib_pln.metta`

Note: `/PeTTa/lib/lib_pln.metta` also exists in the image but is a DIFFERENT file
(sha256 `6b980321...`). The spec pins "verbatim from omegaclaw:v0.1.23-6376e99" per the
Omega repos layout, and `deploy/omega/plugins/metta-grammar` is backed by the
`/PeTTa/repos/Omega` pair — so the `/PeTTa/repos/Omega` pair is the provenance source.
Decision recorded in state.md 2026-11-03 13:1x UTC.

## Staged files (memory/openclaw-das-bridge-campaign/staging/metta-libs/)

sha256, staged vs in-image (docker exec omega-curiosity sha256sum), byte-identical:

| File         | Staged sha256 (local)                        | In-image sha256                               | Match |
|--------------|----------------------------------------------|-----------------------------------------------|-------|
| lib_nal.metta | 3f2894d9b1bc4e39fd7d0384aa6c8503b847eed38826222941ffa14dc0610283 | 3f2894d9b1bc4e39fd7d0384aa6c8503b847eed38826222941ffa14dc0610283 | YES |
| lib_pln.metta | 05b63266ad79c3cd0b32a83a4596ad47923e612e746303628da7500bbcffa7ae | 05b63266ad79c3cd0b32a83a4596ad47923e612e746303628da7500bbcffa7ae | YES |

## Destination (after S2 worker acceptance)

Commit verbatim into `deploy/openclaw-sut/metta-libs/` in
`/home/claw/.openclaw/workspace/repos/openclaw-distributed-atomspace-bridge`
(worker's README there documents `Dockerfile.sut` COPYs exactly these two files into
`/opt/sut-metta/`; deploy.sh stage 2 fails fast while they are missing — by design).

Commit AFTER the coder-opencode ACP turn finishes, to avoid git index contention with
its in-flight per-phase commits. Re-verify sha256 immediately before committing
(`sha256sum` against the table above) and re-run the same comparison inside the image
if more than ~24h elapse before commit.
