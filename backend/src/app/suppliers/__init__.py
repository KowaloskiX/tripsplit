"""Structured supplier data: search and price quotes without a browser agent or an LLM.

Each supplier module turns a supplier's own JSON API into plain dataclasses. Purchases stay
with the booking agent (`app.agent`) — these clients only read.
"""
