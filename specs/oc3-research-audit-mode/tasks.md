# Tasks — Research Q&A audit mode

- [x] T1. P1: `question_pack.py` loader/validator (schema `question-pack/1`,
      unique ids, non-empty question, TEST_CASES id collision guard); wire
      `--battery` to accept path-or-`battery`; unit tests.
- [x] T2. P2: faithfulness judge prompt template + selection seam
      (no-expected-answer case → faithfulness); unit tests for both paths.
- [x] T3. P3: battery prompt template live-retrieve contract
      (retrieve-before-FACTS); standard prompts untouched; unit test.
- [x] T4. P4: fixture-pack end-to-end battery grading in unit tests; README +
      test-spec docs; full suite green.
