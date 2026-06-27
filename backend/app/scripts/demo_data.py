"""Deterministic fake fitness studio — ~300 customers across all risk bands.

Pure and seeded so it doubles as test fixtures and an offline demo. Produces a
normalized SyncResult and can flatten to a customer-level CSV for upload demos.
"""

from __future__ import annotations

import csv
import io
import random
from datetime import datetime, timedelta

from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
    SyncResult,
)

FIRST = [
    "Jordan", "Sam", "Alex", "Riya", "Noah", "Maya", "Liam", "Ava", "Ethan",
    "Sofia", "Mason", "Isla", "Lucas", "Mia", "Leo", "Zoe", "Kai", "Nora",
]
LAST = [
    "Lee", "Rivera", "Patel", "Nguyen", "Kim", "Garcia", "Cohen", "Okafor",
    "Silva", "Haddad", "Romano", "Singh", "Brooks", "Flores", "Walsh",
]


def generate_sync(n: int = 300, seed: int = 42, now: datetime | None = None) -> SyncResult:
    rng = random.Random(seed)
    now = now or datetime.utcnow()
    result = SyncResult()

    # Risk archetypes -> (last-visit gap as multiple of interval) and weight.
    archetypes = [
        ("healthy", 0.6, 0.45),   # visiting on cadence
        ("slipping", 1.8, 0.25),  # ~yellow
        ("at_risk", 3.2, 0.20),   # ~red
        ("gone", 6.0, 0.10),      # long gone
    ]

    for i in range(n):
        first = rng.choice(FIRST)
        last = rng.choice(LAST)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        phone = f"+1555{rng.randint(1000000, 9999999)}"
        interval = rng.uniform(3.0, 9.0)  # days between gym visits
        tenure_days = rng.uniform(90, 900)
        joined = now - timedelta(days=tenure_days)

        archetype, gap_mult, _ = rng.choices(
            archetypes, weights=[w for *_, w in archetypes], k=1
        )[0]
        last_visit = now - timedelta(days=interval * gap_mult)

        ext = f"cust-{i}"
        result.customers.append(
            NormalizedCustomer(
                external_id=ext,
                source="csv",
                first_name=first,
                last_name=last,
                email=email,
                phone=phone,
                created_at=joined,
            )
        )

        # Walk visits backward from last_visit to joined.
        t = last_visit
        while t > joined:
            result.visits.append(
                NormalizedVisit(
                    source="csv",
                    customer_external_id=ext,
                    customer_email=email,
                    occurred_at=t,
                )
            )
            result.transactions.append(
                NormalizedTransaction(
                    source="csv",
                    customer_external_id=ext,
                    customer_email=email,
                    amount=round(rng.uniform(12, 45), 2),
                    occurred_at=t,
                )
            )
            t = t - timedelta(days=interval * rng.uniform(0.7, 1.3))

    return result


def to_customer_csv(sync: SyncResult) -> str:
    """Flatten to one aggregate row per customer (last visit + lifetime spend)."""
    last_visit: dict[str, datetime] = {}
    spend: dict[str, float] = {}
    for v in sync.visits:
        key = v.customer_external_id or v.customer_email or ""
        if key and (key not in last_visit or v.occurred_at > last_visit[key]):
            last_visit[key] = v.occurred_at
    for t in sync.transactions:
        key = t.customer_external_id or t.customer_email or ""
        if key:
            spend[key] = spend.get(key, 0.0) + float(t.amount)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["first_name", "last_name", "email", "phone", "join_date", "last_visit", "total_spent"]
    )
    for c in sync.customers:
        key = c.external_id or c.email or ""
        lv = last_visit.get(key)
        w.writerow([
            c.first_name or "",
            c.last_name or "",
            c.email or "",
            c.phone or "",
            c.created_at.date().isoformat() if c.created_at else "",
            lv.date().isoformat() if lv else "",
            f"{spend.get(key, 0.0):.2f}",
        ])
    return buf.getvalue()
