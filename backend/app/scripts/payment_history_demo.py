"""Provider-shaped sample payment histories for safe end-to-end retention QA.

The official Stripe and Square sandboxes require account credentials. This module
keeps local/CI tests credential-free while deliberately passing data through the
same provider parsers used in production.

    python -m app.scripts.payment_history_demo --provider both --customers 40
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from app.integrations.square_adapter import parse_square_customer, parse_square_payment
from app.integrations.stripe_adapter import parse_stripe_charge, parse_stripe_customer
from app.schemas.normalized import NormalizedVisit, SyncResult
from app.scripts.demo_data import generate_sync
from app.services.activity import build_scored_customers, monthly_revenue_series, summarize


def _visit(transaction) -> NormalizedVisit:
    return NormalizedVisit(
        external_id=f"visit-{transaction.external_id}",
        source=transaction.source,
        customer_external_id=transaction.customer_external_id,
        customer_email=transaction.customer_email,
        customer_phone=transaction.customer_phone,
        occurred_at=transaction.occurred_at,
    )


def generate_provider_sync(
    provider: str,
    *,
    n: int = 40,
    seed: int = 42,
    now: datetime | None = None,
) -> SyncResult:
    """Generate realistic provider payloads, then normalize through real parsers."""
    provider = provider.lower().strip()
    if provider not in {"stripe", "square"}:
        raise ValueError("provider must be 'stripe' or 'square'")
    now = now or datetime.now(UTC)
    base = generate_sync(n=n, seed=seed, now=now)
    result = SyncResult()
    provider_customer_ids: dict[str, str] = {}

    for index, customer in enumerate(base.customers):
        base_id = customer.external_id or f"cust-{index}"
        provider_id = f"cus_demo_{index}" if provider == "stripe" else f"SQ-DEMO-{index}"
        provider_customer_ids[base_id] = provider_id
        if provider == "stripe":
            parsed = parse_stripe_customer(
                {
                    "id": provider_id,
                    "name": customer.full_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "created": int((customer.created_at or now).timestamp()),
                }
            )
        else:
            parsed = parse_square_customer(
                {
                    "id": provider_id,
                    "given_name": customer.first_name,
                    "family_name": customer.last_name,
                    "email_address": customer.email,
                    "phone_number": customer.phone,
                    "created_at": (customer.created_at or now).astimezone(UTC).isoformat(),
                }
            )
        result.customers.append(parsed)

    for index, transaction in enumerate(base.transactions):
        base_id = transaction.customer_external_id or ""
        customer_id = provider_customer_ids.get(base_id)
        cents = int(round(float(transaction.amount) * 100))
        if provider == "stripe":
            parsed_tx = parse_stripe_charge(
                {
                    "id": f"ch_demo_{index}",
                    "status": "succeeded",
                    "amount": cents,
                    "amount_refunded": 0,
                    "currency": "usd",
                    "customer": customer_id,
                    "created": int(transaction.occurred_at.timestamp()),
                    "billing_details": {"email": transaction.customer_email},
                }
            )
        else:
            timestamp = transaction.occurred_at.astimezone(UTC).isoformat()
            parsed_tx = parse_square_payment(
                {
                    "id": f"PAY-DEMO-{index}",
                    "status": "COMPLETED",
                    "amount_money": {"amount": cents, "currency": "USD"},
                    "customer_id": customer_id,
                    "buyer_email_address": transaction.customer_email,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )
        if parsed_tx is not None:
            result.transactions.append(parsed_tx)
            if parsed_tx.is_revenue:
                result.visits.append(_visit(parsed_tx))

    # A recent unresolved failure exercises the hard lifecycle risk boost.
    customer = result.customers[0]
    if provider == "stripe":
        failed = parse_stripe_charge(
            {
                "id": "ch_demo_failed",
                "status": "failed",
                "failure_code": "card_declined",
                "amount": 2500,
                "currency": "usd",
                "customer": customer.external_id,
                "created": int((now - timedelta(days=1)).timestamp()),
                "billing_details": {"email": customer.email},
            }
        )
    else:
        failed = parse_square_payment(
            {
                "id": "PAY-DEMO-FAILED",
                "status": "FAILED",
                "amount_money": {"amount": 2500, "currency": "USD"},
                "customer_id": customer.external_id,
                "buyer_email_address": customer.email,
                "created_at": (now - timedelta(days=1)).isoformat(),
                "updated_at": (now - timedelta(days=1)).isoformat(),
            }
        )
    if failed is not None:
        result.transactions.append(failed)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("stripe", "square", "both"), default="both")
    parser.add_argument("--customers", type=int, default=40)
    args = parser.parse_args()

    providers = ("stripe", "square") if args.provider == "both" else (args.provider,)
    for provider in providers:
        sync = generate_provider_sync(provider, n=args.customers)
        scored = build_scored_customers(sync, vertical="cafe")
        summary = summarize(scored, monthly_revenue_series(sync))
        payment_issues = sum(1 for customer in scored if customer.payment_issue)
        print(
            f"{provider.title()}: {summary.total_customers} customers, "
            f"{len(sync.transactions)} payments, {summary.high_risk} high risk, "
            f"{payment_issues} unresolved payment issue(s), "
            f"${summary.revenue_at_risk:,.0f}/yr at risk"
        )


if __name__ == "__main__":
    main()
