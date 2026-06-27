"""Seed an offline demo. Prints the onboarding "money screen" and writes a sample
CSV you can upload through the UI. Runs with zero infrastructure.

    uv run python -m app.scripts.seed
"""

from __future__ import annotations

from pathlib import Path

from app.scripts.demo_data import generate_sync, to_customer_csv
from app.services.activity import build_scored_customers, summarize


def main() -> None:
    sync = generate_sync(n=300)
    scored = build_scored_customers(sync, vertical="fitness")
    summary = summarize(scored)

    out = Path(__file__).with_name("sample_customers.csv")
    out.write_text(to_customer_csv(sync))

    print("Seeded fake fitness studio")
    print(f"  customers:        {summary.total_customers}")
    print(f"  high risk:        {summary.high_risk}")
    print(f"  medium risk:      {summary.med_risk}")
    print(f"  low risk:         {summary.low_risk}")
    print(f"  revenue at risk:  ${summary.revenue_at_risk:,.0f}/yr")
    print("\nThe money screen:")
    print(
        f'  "We found {summary.high_risk} customers at high risk, '
        f'worth an estimated ${summary.revenue_at_risk:,.0f}/year."'
    )
    print(f"\nWrote {out.name} ({summary.total_customers} rows) — upload it via onboarding.")

    print("\nTop 3 at-risk customers and why:")
    for s in sorted(scored, key=lambda x: x.result.score, reverse=True)[:3]:
        print(f"  • {s.customer.full_name} ({s.result.score}, {s.result.band})")
        for r in s.result.reasons[:2]:
            print(f"      - {r}")


if __name__ == "__main__":
    main()
