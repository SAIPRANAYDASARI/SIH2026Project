# Evaluation harness

The full golden-set evaluation harness (150+ JSONL questions, all seven
intents, both audiences, citation/refusal metrics, head-to-head config
comparison, regression-gated CI mode) is built in Step 12, after the answer
engine exists to evaluate. See section 11 of the build brief and
`docs/EVALUATION.md` (fleshed out in that step).

`golden_set_sample.jsonl` is a much smaller, earlier artifact: ~10 questions
used by Step 4's `python -m app.retrieval.cli baseline` to report raw
retrieval recall@k/MRR *before any LLM is involved*, per the brief's
step-ordering instructions. Each line is
`{"query": "...", "expected_is_numbers": ["IS ..."]}`. It is not a subset
of, or a replacement for, the Step 12 golden set — that one needs its own
much larger, more carefully curated set covering every intent, both
audiences, and adversarial/refusal cases, which this sample deliberately
doesn't attempt.
