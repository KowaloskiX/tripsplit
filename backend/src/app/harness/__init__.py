"""The trip harness: whole group trips driven end to end through the real services and database.

A scenario (`app.harness.scenarios.<name>.SCENARIO`) reads like a test plan; the driver executes
it step by step against a fresh database, checks the invariants after every step and writes a
Markdown + JSON report. Product code is driven, never modified: a missing feature makes the
step `pending`, a known bug is a recorded finding.
"""
