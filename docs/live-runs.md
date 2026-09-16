# Live runs: how to produce and publish one

**No live run has been made yet.** Nothing in this repository has called
Gemini, Claude or OpenAI. This page is the procedure for the first run and
the template for its report, so that a result, when it exists, says exactly
what produced it.

## Before you start

- Budget: each case calls the agent model 1–3 times, and the rubric metric
  calls the judge `num_samples` (3) times per invocation. Eight cases, nine
  invocations.
- The judge is Gemini (`evals/test_config.json`, `judge_model`). You need
  `GOOGLE_API_KEY` or Vertex credentials even when the agent runs on Claude
  or OpenAI.
- The judge id `gemini-3.5-flash` matched ADK 2.9.1's default model when it
  was written and has **not** been checked against the live API. If it is
  rejected, edit `judge_model` (or copy the config and pass
  `EVAL_CONFIG=...`) and write down which judge you used.
- A Gemini judge grading a Gemini agent can be biased toward its own family.
  When comparing providers, keep the judge fixed and say so in the report.

## Run

```bash
mkdir -p eval_results
make seed                       # fresh synthetic data: the references assume it
make eval 2>&1 | tee eval_results/$(date +%F)-gemini-default.log
WMS_MODEL_BACKEND=litellm WMS_MODEL=anthropic/<model-id> \
  make eval 2>&1 | tee eval_results/$(date +%F)-anthropic.log
```

`eval_results/` is ignored by git on purpose: raw logs can be large. Copy the
numbers you want to keep into a report (below). Or run the manual
`eval-live` GitHub workflow, which uploads the log as an artifact.

Also try the two conversations every reviewer will ask about, with
`make run` (writes off) and `make run POLICY=dry_run`:

1. "What's the status of Martínez's order?" → should list four candidates and
   ask; then answer "10412" → should report order 10412 only.
2. "Mark order 10432 as a stock issue, the gloves are short." with
   `POLICY=dry_run` → the approval prompt shows the order id, status and
   reason; approving returns `dry_run` and the agent says nothing was written.

This also checks that the provider accepts the tool schemas ADK sends
(`anyOf`/`null`, `additionalProperties: false`), which no offline test can.

## Report template

Save as `docs/live-runs/<date>-<model>.md` and link it from the README.

```markdown
# <date>: <model id> (backend <gemini|litellm>)

- Commit: <sha>
- Instruction: adk-wms-assistant/v<N>
- google-adk <x>, litellm <x>, judge <model id>, num_samples <n>
- Runs: <how many times make eval was run>; do not extrapolate beyond them

| Case | trajectory | response_match | asks_when_ref_asks | no_extra_tools | rubric |
|---|---|---|---|---|---|
| ... | | | | | |

## One failure, analysed
What the model did, why the metric failed, and whether the metric or the
agent is wrong.

## Transcript (adk run, Martínez case)
<paste>
```
