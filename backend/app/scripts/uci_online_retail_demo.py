"""Run real UCI retail transactions through Churnary's scoring pipeline.

Example:
    uv run python -m app.scripts.uci_online_retail_demo \
      "/path/to/Online Retail.xlsx" --customers 60
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from app.integrations.uci_online_retail import (
    export_sample_csv,
    parse_online_retail_xlsx,
    rebase_sync,
)
from app.services.activity import build_scored_customers, monthly_revenue_series, summarize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook")
    parser.add_argument("--customers", type=int, default=60)
    parser.add_argument("--transactions-per-customer", type=int, default=48)
    parser.add_argument("--fixture", help="Optional path for a compact invoice-level CSV subset")
    parser.add_argument("--preserve-dates", action="store_true")
    args = parser.parse_args()

    sync = parse_online_retail_xlsx(
        args.workbook,
        max_customers=args.customers,
        max_transactions_per_customer=args.transactions_per_customer,
    )
    if args.fixture:
        export_sample_csv(sync, args.fixture)
    if not args.preserve_dates:
        sync = rebase_sync(sync, now=datetime.now(UTC))

    scored = build_scored_customers(sync, vertical="other")
    summary = summarize(scored, monthly_revenue_series(sync))
    refunds = sum(1 for transaction in sync.transactions if transaction.refunded_amount > 0)
    print(sync.warnings[0])
    print(
        f"Scored {summary.total_customers} customers from {len(sync.transactions)} payments: "
        f"{summary.high_risk} high, {summary.med_risk} medium, {summary.low_risk} low risk; "
        f"{refunds} refund/cancellation payments; £{summary.revenue_at_risk:,.0f}/yr at risk."
    )


if __name__ == "__main__":
    main()
