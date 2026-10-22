"""Pulse's own subscription billing: tiers, usage limits, Stripe.

``tiers.py`` and ``limits.py`` are pure — no I/O, no Stripe — so limit
enforcement is testable without a Stripe account and keeps working when Stripe
is unreachable. ``service.py`` is the only module that imports the SDK.
"""
