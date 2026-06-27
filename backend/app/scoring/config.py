"""Per-vertical scoring configuration.

A med-spa client returning after 5 months is normal; a gym member gone 3 weeks is
not. Every weight and threshold lives here so verticals tune independently and the
heuristic stays explainable. Weights need not sum to 1 — the engine normalizes
across whichever signals have data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignalWeights:
    recency: float = 0.40
    frequency: float = 0.25
    monetary: float = 0.15
    engagement: float = 0.10


@dataclass(frozen=True)
class VerticalConfig:
    name: str
    # Expected natural cadence (days) used when a customer has too few visits to
    # derive their own median interval.
    expected_interval_days: float

    weights: SignalWeights = field(default_factory=SignalWeights)

    # Recency gap ratio thresholds (days_since_last / median_interval).
    recency_yellow_ratio: float = 1.5
    recency_red_ratio: float = 2.5

    # Lifecycle adjustments (additive to the 0–100 score).
    new_customer_days: int = 60
    failed_payment_boost: float = 20.0
    cancel_pending_boost: float = 30.0

    # Band cutoffs on the final 0–100 score.
    band_med: float = 40.0
    band_high: float = 70.0


VERTICALS: dict[str, VerticalConfig] = {
    "fitness": VerticalConfig(name="fitness", expected_interval_days=5.0),
    "salon": VerticalConfig(name="salon", expected_interval_days=35.0),
    "med_spa": VerticalConfig(
        name="med_spa",
        expected_interval_days=120.0,
        # Long, lumpy cadence — be slower to alarm.
        recency_yellow_ratio=1.6,
        recency_red_ratio=2.75,
    ),
    "other": VerticalConfig(name="other", expected_interval_days=30.0),
}

DEFAULT_VERTICAL = "other"


def get_vertical_config(vertical: str | None) -> VerticalConfig:
    """Look up a vertical config, falling back to a sane default."""
    if not vertical:
        return VERTICALS[DEFAULT_VERTICAL]
    return VERTICALS.get(vertical.lower().strip(), VERTICALS[DEFAULT_VERTICAL])
