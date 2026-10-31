"""Evals for the booking agent: does the ENGINE work without the model?

Each case is variant x party size x mode, run headless against a local server that renders
the perturbed demo rail sites (`services/demo_supplier_variants`). Success is judged by the
SERVER, not by the agent: the summary it actually rendered must carry the right passenger
count, names, date and train, and nothing may have been paid.

Modes:
  replay      a flow recorded on `baseline` (by the LLM planner, for 6 passengers) + rules
  rules_only  the rule layer alone
  live_llm    the LLM planner (opt-in, capped by `--max-llm-calls`)

`replay` and `rules_only` make ZERO model calls — asserted per case.

    uv run agent-eval run --mode replay
    uv run agent-eval run --mode rules_only --variants baseline,renamed_buttons --party 3
    uv run agent-eval run --mode live_llm --variants baseline,split_pages --party 3
"""
