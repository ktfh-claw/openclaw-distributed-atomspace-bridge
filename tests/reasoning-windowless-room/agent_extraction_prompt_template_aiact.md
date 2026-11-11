# Benchmark Prompt — EU AI Act Articles 1–15 ({{RUN_ID}}) — EXTRACTION PHASE (corpus: aiact)

You are in BENCHMARK MODE (gating test, EXTRACTION phase — shared across all cases).

**This phase is GRADED BY A MACHINE GATE, not by a reader.** The gate requires extraction-record discipline and exact handle accounting; every recorded expression is re-probed against DAS. Do NOT use websearch. Do NOT invent facts.

## The case questions (extraction context)

{{ALL_QUESTIONS}}

These questions are CONTEXT: the knowledge base you build in this phase is what a LATER reasoning phase will answer them from. Extract the corpus sources into DAS now; do NOT answer the questions in this phase.

## The corpus

The corpus is the first 15 articles of the EU AI Act (Regulation (EU) 2024/1689 — Explorer rendering from artificialintelligenceact.eu) as markdown files `article-01.md` .. `article-15.md` in the benchmark background dir (`repos/Omega/memory/benchmark/background/`). Each article file's http(s) source URL is listed in `{{URL_LIST_PATH}}` — those URLs (and ONLY those URLs) are the provenance refs you cite when persisting. Do NOT cite the live site or any other URL.

## TASK LIST — per-PARAGRAPH extraction pipeline, each source exactly once, no other work

**Working memory (binding):** your extraction record `{{FACTS_INDEX_PATH}}` carries state forward — after EVERY `BRIDGE-PERSIST-OK` receipt, immediately `append-file` ONE line `expr <the-exact-expression> top=<handle>` (handle copied verbatim from the receipt). If a result is already recorded, do NOT redo it — reuse the recorded url/handle/expression.

### Phase 1 — EXTRACTION (das-extract-knowledge skill, PER PARAGRAPH)

Follow the **das-extract-knowledge** skill procedure for this phase, applied at PARAGRAPH granularity:

1. Process the article files in ascending order (article-01.md → article-15.md). Read each article ONCE.
2. Chunk each article into paragraph-level units: each paragraph, numbered sub-section (e.g. 1., 2., 3. of an article), or list item of legal text is ONE unit.
3. For EACH unit, derive the MeTTa predicates it grounds — definitions (Art. 3), scope (Art. 1–2), prohibited practices (Art. 5), AI literacy (Art. 4), classification of high-risk systems (Art. 6), registration (Art. 7), data governance (Art. 10), risk management (Art. 9), technical documentation (Art. 11), record-keeping (Art. 12), transparency (Art. 13), human oversight (Art. 14), accuracy/robustness/cybersecurity (Art. 15), and obligations/exceptions/cross-references wherever stated — and persist each predicate via das-write.
4. Cross-paragraph and cross-article consistency: before persisting, check `{{FACTS_INDEX_PATH}}` — if an equivalent expression is already recorded, do NOT persist it again; reuse the recorded expression/handle. Use consistent concept/predicate names across articles (e.g. the same concept for "high-risk AI system", "provider", "deployer", "prohibited practice") instead of near-synonym duplicates.
5. Record every receipt to `{{FACTS_INDEX_PATH}}`, and write the checkpoint manifest when all 15 articles are done.

**Article-level provenance (binding):** cite the source URL of the ARTICLE the paragraph came from (one URL per article file, from `{{URL_LIST_PATH}}`). Paragraph granularity is an extraction-procedure property, not a separate source.

**Persist wiring (binding):** persist each fact via `(metta "(add-atom &persistent (<expression>) \"<source-url>\" (stv 0.9 0.8))")`, where `<source-url>` is that article's URL from `{{URL_LIST_PATH}}` — the write bridge accepts http(s) URL refs ONLY (container path refs are rejected). Success is ONLY `BRIDGE-PERSIST-OK: verified=<n> top=<handle>`: a fact without a fresh receipt is NOT persisted — never record it, never claim progress beyond your receipts, and never write the checkpoint manifest or claim STOP unless the receipts and the manifest write actually succeeded.

### Checkpoint manifest (phase boundary)

The checkpoint manifest is the phase boundary between extraction and reasoning: the extraction phase writes it (recording the extracted predicates, their write receipts/handles, sources, and a timestamp), and the reasoning phase reads it as its entry point into the knowledge base. The manifest lives in the Omega memory volume at `/PeTTa/repos/Omega/memory/knowledge-checkpoints/` (one manifest per corpus). After the extraction phase completes (all 15 articles, all paragraphs, all receipts recorded), write the checkpoint manifest recording what was extracted; the reasoning phase reads it to know which predicates exist, verbatim, for query reuse.

### STOP rule

The extraction phase is DONE when the checkpoint manifest is written to `/PeTTa/repos/Omega/memory/knowledge-checkpoints/`. STOP means: no more tool calls, no more sends, no verification re-reads, no file rewrites. A later wake cycle that finds the manifest already written must do NOTHING — the case is graded by the harness, not by you. Idle silently until the next question arrives.
