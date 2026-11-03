# metta-libs — vendored NAL/PLN libraries (upstream Omega, orchestrator-committed)

`Dockerfile.sut` COPYies exactly two files from this directory into
`/opt/sut-metta/` in the SUT wrapper image:

- `lib_nal.metta`
- `lib_pln.metta`

**This is an orchestrator task** (spec tasks.md): fetch the two files
from UPSTREAM, commit them here byte-identical, and only then run
`deploy.sh` (stage 2 fails fast while they are missing, by design — a
wrapper image without the libraries would silently break the metta
skill: the pinned runtime does not fail a failed `import!`, the form
just yields no results and the eval returns unevaluated garbage).

## Provenance (authoritative — spec addendum item 4)

The files originate from **upstream Omega**,
https://github.com/singnet/Omega.git — the same libraries that back the
Omega agent's NAL/PLN strictly-2-argument operators. Omega's own
`run.metta` pulls itself via `!(git-import! "https://github.com/singnet/Omega.git")`,
i.e. upstream Omega is the canonical source of these files, pinned at:

- repo: https://github.com/singnet/Omega.git
- commit: `b94f7bf44e10852e491967191f1c68643dc9ca90` (HEAD at 2026-11-03)
- files: `lib_nal.metta`, `lib_pln.metta` (repo root)

Vendored copies, sha256 (verified byte-identical to upstream at the
pinned commit on 2026-11-03):

| File          | sha256                                                              |
| ------------- | ------------------------------------------------------------------- |
| `lib_nal.metta` | `3f2894d9b1bc4e39fd7d0384aa6c8503b847eed38826222941ffa14dc0610283` |
| `lib_pln.metta` | `05b63266ad79c3cd0b32a83a4596ad47923e612e746303628da7500bbcffa7ae` |

## Anyone-can-repeat fetch (the provisioning path)

```bash
git clone https://github.com/singnet/Omega.git
cd Omega
git checkout b94f7bf44e10852e491967191f1c68643dc9ca90
sha256sum lib_nal.metta lib_pln.metta
# must print:
#   3f2894d9b1bc4e39fd7d0384aa6c8503b847eed38826222941ffa14dc0610283  lib_nal.metta
#   05b63266ad79c3cd0b32a83a4596ad47923e612e746303628da7500bbcffa7ae  lib_pln.metta
```

If the sha256s match, the fetch is byte-identical to the vendored
copies — commit them verbatim. If they ever differ (upstream moved and
the pin with it), re-pin deliberately in the spec, never silently.

## The omega container is a cross-check, NOT the provisioning path

The running `omegaclaw:v0.1.23-6376e99` image carries the same pair at
`/PeTTa/repos/Omega/` and may be used to CROSS-CHECK the vendored bytes
(`docker exec omega-curiosity sha256sum /PeTTa/repos/Omega/lib_nal.metta
/PeTTa/repos/Omega/lib_pln.metta` — must match the table above), but
it is never the source of the committed files: extraction from an
omega-built artifact is not repeatable by anyone, upstream is.

## Do not use PeTTa's own PLN lib

PeTTa v1.0.4 ships its own `lib/lib_pln.metta` (different sha256
`6b980321…`). The benchmark arm's PLN contract is **Omega's copy** —
the file vendored here — exactly as in the omegaclaw image.

Provenance rule: the files must stay byte-identical to upstream Omega at
the pinned commit — any local edit would fork the reasoning contract
between the two benchmark arms.
