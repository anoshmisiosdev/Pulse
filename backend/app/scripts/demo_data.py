"""Deterministic fake coffee shop — "Hayward Coffee Co.", ~50 customers across all
risk bands. Pure and seeded so it doubles as test fixtures and an offline demo.
Produces a normalized SyncResult and can flatten to a customer-level CSV.
"""

from __future__ import annotations

import csv
import io
import random
from datetime import UTC, datetime, timedelta

from app.schemas.normalized import (
    NormalizedCustomer,
    NormalizedTransaction,
    NormalizedVisit,
    SyncResult,
)

DEMO_BUSINESS_NAME = "Hayward Coffee Co."
DEMO_VERTICAL = "cafe"

FIRST = [
    "Amara", "Ravi", "Kevin", "Zara", "Aaliyah", "Mei-Ling", "Jonas", "Adrian",
    "Luis", "Isabella", "Simone", "Theo", "Ryan", "Nadia", "Marcus", "Priya",
    "Diego", "Hana", "Omar", "Elena", "Tomas", "Yuki", "Andre", "Leila",
]
LAST = [
    "Nwosu", "Patel", "Okafor", "Mensah", "Brown", "Zhou", "Weber", "Torres",
    "Castillo", "Ferreira", "Adeyemi", "Nakamura", "Cho", "Khan", "Silva",
    "Romano", "Haddad", "Flores", "Walsh", "Kim",
]
MENU = [
    ("Oat Milk Latte", 5.25),
    ("Lavender Oat Latte", 5.75),
    ("Almond Croissant", 4.75),
    ("Avocado Toast", 9.50),
    ("Chai Latte", 4.95),
    ("Matcha Latte", 5.50),
    ("Cold Brew", 4.50),
    ("Espresso", 3.25),
    ("Cappuccino", 4.75),
    ("Drip Coffee", 3.00),
]


def generate_sync(n: int = 50, seed: int = 42, now: datetime | None = None) -> SyncResult:
    rng = random.Random(seed)
    now = now or datetime.now(UTC)
    result = SyncResult()

    # Risk archetypes -> (last-visit gap as multiple of interval, weight).
    archetypes = [
        ("healthy", 0.6, 0.40),   # visiting on cadence
        ("slipping", 1.9, 0.25),  # ~yellow
        ("at_risk", 3.4, 0.20),   # ~red
        ("gone", 7.0, 0.10),      # long gone
        ("new", 0.8, 0.05),       # joined recently
    ]

    for i in range(n):
        first = rng.choice(FIRST)
        last = rng.choice(LAST)
        email = f"{first.lower().replace('-', '')}.{last.lower()}{i}@example.com"
        phone = f"+1555{rng.randint(1000000, 9999999)}"
        favorite, unit_price = rng.choice(MENU)
        interval = rng.uniform(2.5, 7.0)  # days between coffee runs

        archetype, gap_mult, _ = rng.choices(
            archetypes, weights=[w for *_, w in archetypes], k=1
        )[0]

        tenure_days = rng.uniform(20, 50) if archetype == "new" else rng.uniform(120, 800)
        joined = now - timedelta(days=tenure_days)
        last_visit = now - timedelta(days=interval * gap_mult)
        if last_visit < joined:
            last_visit = joined + timedelta(days=interval)

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
                favorite_item=favorite,
            )
        )

        # Walk visits backward from last_visit to joined.
        t = last_visit
        while t > joined:
            result.visits.append(
                NormalizedVisit(
                    source="csv", customer_external_id=ext, customer_email=email, occurred_at=t
                )
            )
            # A coffee run is usually the favorite plus the odd pastry.
            spend = unit_price + (rng.choice([0, 0, 0, 3.0, 4.75]) if rng.random() < 0.4 else 0)
            result.transactions.append(
                NormalizedTransaction(
                    source="csv",
                    customer_external_id=ext,
                    customer_email=email,
                    amount=round(spend, 2),
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
        ["first_name", "last_name", "email", "phone", "join_date",
         "last_visit", "total_spent", "favorite_item"]
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
            c.favorite_item or "",
        ])
    return buf.getvalue()
