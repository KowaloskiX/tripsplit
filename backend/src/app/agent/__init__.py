"""The booking agent: a browser-driving loop that fills supplier checkouts for the group.

    observe -> decide -> act -> recover -> repeat

Ported from the hackathon purchase agent. The planner (an LLM with vision) sees a screenshot
plus a compact list of interactive elements and returns exactly ONE action per step. Secrets
never enter the model: the planner emits `{{vault.key}}` placeholders and `act.py` substitutes
the real values at action time.

Hard rule: the agent stops BEFORE the final "pay" click (`stop_before_pay`) and hands the
fully populated summary back to a human, who approves it in the UI. CAPTCHA, OTP and 3-D Secure
are never fought — they trigger `handoff`.

This package is infrastructure at the edge (Playwright, OpenAI). It is driven by
`app.services` and must not import routes, schemas or the database.
"""
