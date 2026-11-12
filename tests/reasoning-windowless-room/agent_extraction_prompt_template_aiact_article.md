# Benchmark Prompt — EU AI Act {{ARTICLE_STEM}} ({{RUN_ID}}) — EXTRACTION PHASE (corpus: aiact, per-article turn)

You are in BENCHMARK MODE (gating test, EXTRACTION phase — ONE article of the EU AI Act corpus).

**This phase is GRADED BY A MACHINE GATE, not by a reader.** The gate polls the checkpoint manifest for this article's completion line and re-probes every recorded expression against DAS. Do NOT use websearch. Do NOT invent facts.

## The case questions (extraction context)

{{ALL_QUESTIONS}}

These questions are CONTEXT: the knowledge base you build across the article turns is what a LATER reasoning phase will answer them from. Extract THIS article now; do NOT answer the questions in this phase.

## THIS turn's scope — exactly ONE article

- Article file: `{{ARTICLE_FILE}}` in the benchmark background dir (the corpus files sit beside it; do NOT re-extract other articles in this turn).
- Source URL (provenance ref for EVERY predicate you persist from this article): `{{ARTICLE_URL}}` — and ONLY this URL. Do NOT cite the live site, container paths, or any other URL.

## FIRST action (idempotency)

Read the checkpoint manifest `/PeTTa/repos/Omega/memory/knowledge-checkpoints/aiact-extraction.md` (create it only later, when you append). If it already contains a line starting `ARTICLE-COMPLETE:` that names `{{ARTICLE_STEM}}`, this article is ALREADY done — do NOTHING further in this turn (the harness gate owns grading). Otherwise proceed.

## TASK — per-PARAGRAPH extraction of {{ARTICLE_STEM}}

Follow the **das-extract-knowledge** skill procedure at PARAGRAPH granularity:

1. Read `{{ARTICLE_FILE}}` ONCE.
2. Chunk it into paragraph-level units: each paragraph, numbered sub-section (e.g. 1., 2., 3. of the article), or list item of legal text is ONE unit.
3. For EACH unit, derive the MeTTa predicates it grounds — definitions, scope, prohibitions, obligations, exceptions, cross-references, effective dates wherever stated — and persist each predicate via das-write.
4. Consistency and dedup (binding): before persisting, check your extraction record `{{FACTS_INDEX_PATH}}` — if an equivalent expression is already recorded (from THIS or an EARLIER article), do NOT persist it again; reuse the recorded expression/handle. Use consistent concept/predicate names across articles (the same concept for "high-risk AI system", "provider", "deployer", "prohibited practice") instead of near-synonym duplicates.

## Persist wiring (binding — read this twice)

Persist each predicate via:

```
(metta "(add-atom &persistent (<expression>) \"{{ARTICLE_URL}}\" (stv 0.9 0.8))")
```

- The write bridge accepts http(s) URL refs ONLY; it FETCHES the URL and hashes the bytes — `{{ARTICLE_URL}}` is the article file's committed corpus URL.
- **QUOTE ESCAPING (hard requirement):** the whole add-atom call is a string INSIDE `(metta "...")`. EVERY literal double-quote character of the call must be written `\"` inside that string. A scripted/batch persist that emits raw quotes produces `BRIDGE-PERSIST-WRITE-FAILED: expected one balanced expression after &persistent` on EVERY line (12 consecutive such failures were observed in a previous run — the self-written batch helper did not escape quotes).
- **One das-write call per predicate, inline.** Do NOT write or run batch/scripts that build many persist calls — if you use any scripted helper, verify EVERY emitted call has every inner quote escaped `\"` before running it, and prefer inline single persists over batching.
- Success is ONLY `BRIDGE-PERSIST-OK: verified=<n> top=<handle>`: a fact without a fresh receipt is NOT persisted — never record it, never claim progress beyond your receipts.

## Extraction record (binding)

After EVERY `BRIDGE-PERSIST-OK` receipt, IMMEDIATELY `append-file` ONE line to `{{FACTS_INDEX_PATH}}`:

```
expr <the-exact-expression> top=<handle>
```

(handle copied verbatim from the receipt; the expression with `\"` escapes exactly as persisted). No batching of record lines; one line per receipt, appended at once. This record carries dedup state forward to the later articles and the reasoning phase.

## Checkpoint manifest (turn boundary)

When — and only when — every paragraph unit of `{{ARTICLE_STEM}}` has its predicates persisted (receipts OK) and recorded: `append-file` to `/PeTTa/repos/Omega/memory/knowledge-checkpoints/aiact-extraction.md` (create it if it is your first append) a short section for this article: the extracted predicate expressions, their handles, the source URL, and a timestamp — ending the section with EXACTLY ONE completion line in this format (the machine gate greps it):

```
ARTICLE-COMPLETE: {{ARTICLE_STEM}} <ISO-8601 UTC timestamp> <n> predicates
```

## STOP rule

After the `ARTICLE-COMPLETE:` line is appended, STOP: no more tool calls, no verification re-reads, no file rewrites. A later wake cycle that finds the line already present must do NOTHING — the case is graded by the harness, not by you. Idle silently until the next question arrives.
