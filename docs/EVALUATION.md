# Evaluation

Two harnesses exist, deliberately kept separate because they measure
different things:

## 1. Baseline retrieval metrics (Step 4, no LLM in the loop)

`app.retrieval.baseline_eval` / `python -m app.retrieval.cli baseline`
computes recall@k and MRR against `eval/golden_set_sample.jsonl` (~10
questions), fused (pre-rerank) and reranked, using only BM25+dense+RRF+rerank
— no LLM calls at all. This establishes "is retrieval good enough" before
the answer engine exists to build on top of it, per the brief's step
ordering.

## 2. Full-pipeline evaluation (Step 12, this file's main scope)

`app.eval.full_eval` runs each question in `eval/golden_set_full.jsonl`
through the *complete* answer engine (`app.answer.engine.answer_query`:
retrieval + LLM + citation validation + guardrails) and reports:

- **Intent accuracy** — does `query_understanding`'s classified intent
  match the golden label.
- **Citation precision** — of questions expected to carry a citation, the
  fraction whose answer has at least one resolved `[N]` citation and zero
  invalid markers.
- **Forced-refusal accuracy** / **false-refusal rate** — of genuinely
  out-of-scope questions, how many correctly triggered the forced-refusal
  path (`AnswerResult.forced_refusal`); and of answerable questions, how
  many were wrongly refused.
- **Average latency** — mean end-to-end `AnswerResult.latency_ms`.

Run it against a live stack (Postgres + reranker + a configured LLM
backend, same prerequisites as `app.answer.cli ask`):

```bash
docker compose exec backend python -m app.eval.cli run
```

### Scope note: golden set size

The original build brief describes a 150+-question golden set. What ships
in `eval/golden_set_full.jsonl` is a much smaller, hand-curated set of 26
questions — chosen to cover every `Intent` value
(`standard_lookup`, `product_to_standard`, `scheme_eligibility`,
`process_howto`, `verification`, `consumer_safety`, `out_of_scope`) across
both audiences, plus deliberate refusal cases. A genuinely 150+-question
set needs subject-matter-expert review of each expected answer at a scale
this hackathon build's time budget doesn't cover — the harness itself
(`app.eval.full_eval.run_full_eval`) scales to any size input and would
need no code changes to run against a larger, more rigorously curated set
later. See `docs/DECISIONS.md`, Step 12.

### What this harness does *not* measure

Groundedness here is a proxy (no fabricated `[N]` marker), not a factual
accuracy check against BIS's actual current rules — that needs human
review of each answer against a primary source, which is out of scope for
an automated harness. The citation-precision number should be read as "the
model didn't hallucinate a source", not "the model was factually correct".

### CI regression gate

Not wired into CI in this build — running the full harness needs a live
LLM backend (a cost/secrets dependency CI doesn't have here). A production
setup would run this nightly against a fixed model/prompt version and
alert on a metric regression past some threshold; flagged as a follow-up,
not implemented.
