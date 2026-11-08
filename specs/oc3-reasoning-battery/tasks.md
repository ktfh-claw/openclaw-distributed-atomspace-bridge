# oc3 — Tasks

## Worker-owned (coder-opencode)
- [ ] P1: BATTERY_CASES in facts.py + 5 prompt .md files (additive only)
- [ ] P2: --battery mode in run_benchmark.py (preflight KB probe, 5-case loop,
      no extraction, no cleanup-das, results/report shape)
- [ ] P3: new unit tests; existing suite green
- [ ] P4: README/test-spec docs section; incremental commit + push per phase
- [ ] Final report: SHAs, test results, diff stat vs main, decisions, deviations

## Orchestrator-owned (main session — do NOT touch)
- [ ] Acceptance review: line-by-line diff vs main; frozen-file empty-diff check
      (grading.py, history_parse.py, provenance_check.py, llm_judge.py,
      background/, existing prompts/, CANONICAL_FACTS/TEST_CASES bodies)
- [ ] Local unit suite re-run on branch worktree
- [ ] Rsync branch to OVH (no --delete; no redeploy needed — harness-only change)
- [ ] Battery smoke + full 5-case battery against live KB on OpenClaw-SUT + DAS
- [ ] RCA on battery FAILs; reasoning-quality proposals
- [ ] Append battery outcomes to manifest GDoc 1QsWbS5xZhLVARvSWCQmPL4JoA7EMgRqqlYLcivQQ7C0
- [ ] Launch oc3 10-run series (oc3a..oc3j) on this branch; monitor; stats GDoc;
      failure-mode RCA + proposals (no implementation)
