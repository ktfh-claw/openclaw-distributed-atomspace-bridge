# metta-libs — vendored NAL/PLN libraries (orchestrator-committed)

`Dockerfile.sut` COPYies exactly two files from this directory into
`/opt/sut-metta/` in the SUT wrapper image:

- `lib_nal.metta`
- `lib_pln.metta`

Both are extracted **verbatim** from the pinned Omega runtime image
`omegaclaw:v0.1.23-6376e99` on the deploy host (the same libraries that
back the Omega agent's NAL/PLN strictly-2-argument operators — see
`deploy/omega/plugins/metta-grammar/metta-grammar.metta`).

**This is an orchestrator task** (spec tasks.md): extract the two files
from the image, commit them here byte-identical, and only then run
`deploy.sh` (stage 2 fails fast while they are missing, by design — a
wrapper image without the libraries would silently break the metta skill).

```bash
# on the OVH host (orchestrator), extract verbatim:
docker create --name omegaclaw-extract omegaclaw:v0.1.23-6376e99
docker cp omegaclaw-extract:/PeTTa/lib_nal.metta ./lib_nal.metta   # path per image layout
docker cp omegaclaw-extract:/PeTTa/lib_pln.metta ./lib_pln.metta
docker rm omegaclaw-extract
# verify both carry the STRICTLY 2-ARGUMENT operator definitions, then commit
```

Provenance rule: the files must stay byte-identical to the Omega image's
copies — any local edit would fork the reasoning contract between the two
benchmark arms.
