# Tasks — oc2-openclaw-native

Worker (coder-opencode) on branch `oc2-openclaw-native` off 08006eb:

- [ ] W1: Recon — read run_benchmark.py end-to-end; inventory every pin
      reference, delivery/session naming, forward-signal census, and the
      phase orchestration seam. Report inventory in the final report.
- [ ] W2: C1 — delete skills-sut/pin/, remove pin from deploy.sh SUT_SKILLS +
      add stale-pin removal, strip pin/ledger refs from both prompt
      templates, keep ADHERENCE_DUPLICATE_BLOCK / drop pin-derived
      conditions. Commit+push.
- [ ] W3: C3+C6+C4 — shared run-level extraction flow, per-phase session
      ids, archive-manifest path outside agent workspace. Commit+push.
- [ ] W4: C5 — forward-signal reads the write-bridge receipts lane. Commit+push.
- [ ] W5: C7 — prompt render tests; answers-block grammar byte-stable in
      template; FACTS bare-expression + REASONING first-step warnings kept.
- [ ] W6: full unit suite green (run_tests.py); new tests for shared-KB
      sequencing, archive path, sidecar lane, session naming, pin-free
      adherence. Commit+push.
- [ ] W7: docs (README updates for harness + deploy); final worker report
      (commits, tests, diff stat vs 08006eb, frozen-diff proof, decisions).

Orchestrator (main session):

- [ ] O1: review worker diff line-by-line + rerun suite locally + frozen-file
      check.
- [ ] O2: rsync to OVH; idempotent deploy.sh re-run (stale pin removal
      verified on live SUT).
- [ ] O3: smoke run of new harness; RCA+fix+retest loop on failures.
- [ ] O4: oc2 10-run series; per-run verdicts; GDoc stats report; share;
      close out cron.
