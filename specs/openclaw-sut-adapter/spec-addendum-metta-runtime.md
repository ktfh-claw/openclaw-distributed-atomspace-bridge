# Spec addendum — upstream-pinned MeTTa runtime for OpenClaw-SUT (R-D2 amendment)

Directive (Balazs, 2026-11-03 14:41 UTC): pull the MeTTa runtime from UPSTREAM at the
same version Omega uses — the deployment must be repeatable by anyone. Do NOT extract
from the omega container.

## RCA (verified live on OVH 2026-11-03 ~15:0x UTC)

Stage-10 smoke failed: `metta_error: hyperon runtime unavailable: cannot import name
'Metta' from 'hyperon'` (pip hyperon 0.2.10). Root cause: the SUT wrapper installs pip
`hyperon`, which was never Omega's runtime. Omega's runtime (per OmegaClaw-Core
Dockerfile @6376e99, branch omega-uplift-v0.1.23) is:

- Base: `docker.io/library/swipl:10.0.2` (SWI-Prolog)
- MeTTa interpreter: **PeTTa v1.0.4** — https://github.com/trueagi-io/PeTTa.git,
  tag `v1.0.4` = commit `7037f4c2ad378c52fc328004fe216d5118b674f0`
  (invocation: `swipl --stack_limit=8g -q -s src/main.pl -- <file>`)
- NAL/PLN libraries: `lib_nal.metta` / `lib_pln.metta` from the Omega source tree;
  upstream origin **https://github.com/singnet/Omega.git** (Omega's own run.metta
  pulls itself via `!(git-import! "https://github.com/singnet/Omega.git")`).
  Current HEAD `b94f7bf4` files are byte-identical to the vendored copies:
  - lib_nal.metta sha256 `3f2894d9b1bc4e39fd7d0384aa6c8503b847eed38826222941ffa14dc0610283`
  - lib_pln.metta sha256 `05b63266ad79c3cd0b32a83a4596ad47923e612e746303628da7500bbcffa7ae`

Comparability proof (decisive): running the upstream recipe
(swipl:10.0.2 + PeTTa v1.0.4 clone + vendored libs via `!(import! &self "<abs>")`)
on `(|- ((--> garfield animal) (stv 1.0 0.9)) ((--> garfield mammal) (stv 1.0 0.9)))`
prints EXACTLY the same result as the omegaclaw:v0.1.23-6376e99 image on the same
input: `(((--> mammal animal) (stv 1.0 0.44751381215469616)) ((<-> mammal animal) ...)
((--> animal mammal) ...) ((<-> animal mammal) ...))` — EXIT=0 both.

Note: PeTTa v1.0.4 ships its OWN `lib/lib_pln.metta` (different sha256
`6b98032…`) — do NOT use it; the benchmark arm's PLN contract is Omega's copy.

## Required changes (worker implementation scope)

1. **Dockerfile.sut** — remove the pip `hyperon` install. Replace with:
   - Multi-stage copy of the pinned SWI-Prolog runtime from the official image:
     `COPY --from=docker.io/library/swipl:10.0.2 /usr/bin/swipl /usr/bin/swipl`
     plus `/usr/lib/swipl*` (verify the actual paths inside swipl:10.0.2 and copy
     everything needed for a working `swipl` in the SUT base; add any required
     shared libs the SUT base lacks, e.g. libtinfo/libreadline — verify at build).
   - Build-time upstream pull of PeTTa, pinned by commit:
     `git clone https://github.com/trueagi-io/PeTTa.git /opt/petta && cd /opt/petta &&
     git checkout 7037f4c2ad378c52fc328004fe216d5118b674f0 && rm -rf .git`
     (needs git in the build stage — install if the base lacks it).
     Do NOT clone faiss/mork/chroma (PeTTa build.sh deps) — only `src/main.pl`
     and its `src/*.pl` siblings are needed for `swipl -s src/main.pl`;
     verify the minimal interpreter needs nothing from PeTTa/build.sh.
   - Keep `COPY metta-libs/... /opt/sut-metta/` (vendored = deterministic; the
     README documents the upstream fetch + sha256 verification for repeatability).
2. **skills-sut/metta/metta_run.py** — replace the hyperon Python API with a
   subprocess call to the pinned runtime:
   - Write a temp .metta file (workspace-local tmp, e.g. `<workspace>/.metta-tmp/`)
     containing `!(import! &self "<lib_dir>/lib_nal.metta")`,
     `!(import! &self "<lib_dir>/lib_pln.metta")`, then `!<expr>`.
   - Invoke `swipl --stack_limit=8g -q -s /opt/petta/src/main.pl -- <tmpfile>`
     (timeout: 120 s) with cwd=/opt/petta (main.pl uses relative src loads).
   - Output contract: drop the interpreter TRACE noise (`--> ... -->` blocks,
     `^^^^` rules, `:- findall(...)` goal echoes, bare `true` lines from the
     imports); the evaluation result = the remaining printed result lines
     (e.g. the derived-atom list). Keep the existing statuses: `syntax_error:`
     / `metta_error:` (nonzero swipl exit or timeout → `metta_error:`), and the
     best-effort history.metta episode append. Keep the `(metta "(...)")`
     unwrap and `!`-prefix handling. Keep: fresh ephemeral atomspace per call
     (a new swipl process per invocation is naturally ephemeral).
   - Empty result prints `()`.
3. **deploy.sh stage 10 smoke** — unchanged assertion (must find `(stv ` in the
   NAL eval output); update the invocation if the smoke calls metta_run.py with
   env overrides (it currently sets OPENCLAW_SUT_WORKSPACE and calls metta_run.py
   with a NAL expression — keep that shape; the libs dir stays /opt/sut-metta).
4. **metta-libs/README.md** — rewrite provenance: files originate from
   https://github.com/singnet/Omega.git (upstream Omega), pinned commit
   `b94f7bf4…` (HEAD at 2026-11-03) with the two sha256s above; document the
   anyone-can-repeat fetch:
   `git clone https://github.com/singnet/Omega.git && git checkout b94f7bf &&
   sha256sum lib_nal.metta lib_pln.metta` (must match), plus the statement that
   the omega container extraction is only a cross-check, NOT the provisioning path.
5. **deploy/openclaw-sut/README.md** — add a "MeTTa runtime provenance" section:
   swipl:10.0.2 official image + PeTTa v1.0.4 (commit 7037f4c2) + libs from
   singnet/Omega @ b94f7bf4, each with upstream URL, pin, and how the build pulls
   them; explicitly: no dependency on any omega-built artifact.
6. **Unit tests** — metta_run.py output filtering (trace noise vs result lines),
   status mapping, unwrap behavior; run the full existing unit suite; gates/
   prompts/deploy/omega/deploy/das MUST remain untouched (diff-free proof).

## Constraints
- No upstream OpenClaw/DAS code changes; bridge-repo only.
- Push to `origin/openclaw-sut-adapter` (existing SDD branch).
- Incremental commits per item (P1 Dockerfile+runtime, P2 metta_run+tests,
   P3 deploy.sh smoke, P4 docs); push after each phase (1800 s turn cap —
   early push so a timeout cannot destroy progress).
- Do NOT deploy to OVH (orchestrator re-runs deploy.sh after acceptance).
