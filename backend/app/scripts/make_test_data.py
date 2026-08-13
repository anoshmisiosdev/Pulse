"""Generate event-level test CSVs with one purpose-built cohort per recommended action.

    cd backend
    .\\.venv\\Scripts\\python.exe -m app.scripts.make_test_data          # all verticals
    .\\.venv\\Scripts\\python.exe -m app.scripts.make_test_data --vertical cafe

Writes to ``testdata/`` at the repo root and prints what each file should produce,
so you can compare the dashboard against the intent rather than guessing.

Why a generator and not checked-in CSVs: scoring is *recency*-based, so absolute
dates rot. A file that describes a healthy regular today describes a churned one in
two months. Every date here is emitted relative to the run date.

Why event-level (one row per visit, repeated email) rather than one row per
customer: the CSV adapter accumulates repeated rows into real visit and transaction
history (``dedupe_customers``), which is what actually exercises the frequency and
monetary signals, the timeline, and the whole action ladder. A customer-level CSV
collapses to a single visit each, so most signals stay switched off.

Cohorts are named in the customer's last name (e.g. "Ana Owner-Call") so you can
verify at a glance that the intended cohort produced the intended action.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.scoring.config import VERTICALS, get_vertical_config

HEADER = "first_name,last_name,email,phone,join_date,date,price,favorite_item"

FIRST_NAMES = [
    "Ana", "Ben", "Cleo", "Dev", "Elena", "Farid", "Gina", "Hugo", "Iris", "Jonas",
    "Kira", "Liam", "Maya", "Noor", "Omar", "Pia", "Quinn", "Rosa", "Sami", "Tara",
    "Uma", "Victor", "Wren", "Xiu", "Yara", "Zane",
]

ITEMS = {
    "cafe": ["Oat flat white", "Cortado", "Almond croissant", "Cold brew", "Chai latte"],
    "salon": ["Balayage", "Cut and finish", "Root touch-up", "Blow dry", "Gloss treatment"],
    "med_spa": ["Hydrafacial", "Botox", "Chemical peel", "Microneedling", "Laser session"],
    "fitness": ["Spin class", "Personal training", "Hot yoga", "Open gym", "Pilates"],
    "other": ["Standard service", "Premium service", "Consultation"],
}


@dataclass
class Visit:
    days_ago: int
    amount: float | None  # None -> no transaction row for this visit


@dataclass
class Cohort:
    """One recommended action, and the customer shape that should produce it."""

    label: str  # becomes the customer's last name
    expect: str  # the action we expect
    count: int
    note: str


def _visits_for(cohort: str, cadence: float, rng: random.Random) -> tuple[int, list[Visit]]:
    """Return (tenure_days, visits) for one customer of this cohort.

    ``cadence`` is the vertical's expected interval, so a salon's "regular" is every
    5 weeks and a cafe's is every few days without special-casing per vertical.
    """
    c = cadence

    if cohort == "Regular":
        # Healthy: on cadence, seen recently, steady spend.
        #
        # The ticket is constant per customer, not jittered per visit. The monetary
        # signal compares the last 90 days against the 90 before that, and a
        # long-cadence vertical fits only one or two visits in each window — so
        # random per-visit amounts make that ratio pure noise and tip a perfectly
        # healthy med-spa regular into "spending less, send an offer".
        ticket = round(rng.uniform(9, 16), 2)
        n = 14
        visits = [Visit(round(i * c) + rng.randint(0, 1), ticket) for i in range(n)]
        return int(n * c) + 40, visits

    if cohort == "Owner-Call":
        # Very high value, long history, then a long absence.
        n = 26
        gone = int(c * 9)
        visits = [
            Visit(gone + round(i * c), round(rng.uniform(48, 85), 2)) for i in range(n)
        ]
        return gone + int(n * c) + 60, visits

    if cohort == "Offer":
        # Still showing up on cadence, but the ticket collapsed. Needs spend in both
        # the recent and prior 90-day windows for the monetary signal to read.
        recent = [Visit(round(i * c) + 1, round(rng.uniform(3, 6), 2)) for i in range(0, 10)]
        prior = [
            Visit(95 + round(i * c), round(rng.uniform(22, 34), 2)) for i in range(0, 12)
        ]
        return 300, recent + prior

    if cohort == "Email":
        # Lapsed with real history, but all of it older than the 90/180-day spend
        # comparison windows, so the monetary signal stays off and this is a plain
        # win-back. Visits are spread widely and priced modestly on purpose:
        # estimated_annual_value annualizes spend over the observed span, so a short
        # dense burst of history inflates these customers into the top quartile and
        # they get recommended for a personal call instead.
        n = 12
        gone = int(c * 6)
        visits = [
            Visit(gone + 200 + round(i * c * 4), round(rng.uniform(7, 12), 2))
            for i in range(n)
        ]
        return gone + 600, visits

    if cohort == "Welcome":
        # Joined inside the new-customer window and already drifting — a brand-new
        # customer who came in yesterday is simply healthy and correctly gets "wait".
        # "Welcome" is for the new customer who tried you twice and never came back.
        #
        # Deliberately NOT scaled by cadence: new_customer_days is a flat 60 across
        # verticals, so a med-spa tenure of 9 × 120 days would age them out of "new"
        # entirely. Two visits a few days apart give them their own short median
        # interval, so the 45-day gap reads as at-risk in every vertical.
        return 55, [
            Visit(50, round(rng.uniform(10, 18), 2)),
            Visit(45, round(rng.uniform(10, 18), 2)),
        ]

    if cohort == "Watch":
        # One visit, long ago, no spend recorded (door-scan style export).
        return 400, [Visit(int(c * 8), None)]

    raise ValueError(f"unknown cohort {cohort}")


COHORTS = [
    Cohort("Regular", "wait", 8, "healthy, on cadence — should be left alone"),
    Cohort("Owner-Call", "owner_call", 5, "top-quartile value, long absence"),
    Cohort("Offer", "offer", 5, "still visiting, spend collapsed"),
    Cohort("Email", "email", 8, "lapsed, history older than the spend windows"),
    Cohort("Welcome", "welcome", 3, "joined recently, thin history"),
    Cohort("Watch", "watch", 3, "one visit, no spend on file"),
]


def build_csv(vertical: str, now: datetime, seed: int = 11) -> str:
    rng = random.Random(seed)
    cfg = get_vertical_config(vertical)
    items = ITEMS.get(vertical, ITEMS["other"])
    lines = [HEADER]
    used: set[str] = set()

    for cohort in COHORTS:
        for i in range(cohort.count):
            first = FIRST_NAMES[(hash(cohort.label) + i * 7) % len(FIRST_NAMES)]
            slug = f"{first}.{cohort.label}".lower().replace("-", "")
            n = 2
            email = f"{slug}@example.com"
            while email in used:  # keep identities unique; dedupe merges by email
                email = f"{slug}{n}@example.com"
                n += 1
            used.add(email)

            phone = f"+1555{rng.randint(1000000, 9999999)}"
            item = rng.choice(items)
            tenure, visits = _visits_for(cohort.label, cfg.expected_interval_days, rng)
            joined = (now - timedelta(days=tenure)).date().isoformat()

            for visit in sorted(visits, key=lambda v: -v.days_ago):
                date = (now - timedelta(days=visit.days_ago)).date().isoformat()
                price = "" if visit.amount is None else f"{visit.amount:.2f}"
                lines.append(
                    f"{first},{cohort.label},{email},{phone},{joined},{date},{price},{item}"
                )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vertical",
        choices=sorted(VERTICALS),
        action="append",
        help="vertical to generate (repeatable; default: cafe, salon, med_spa)",
    )
    parser.add_argument("--out", default=None, help="output directory (default: <repo>/testdata)")
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    verticals = args.vertical or ["cafe", "salon", "med_spa"]
    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parents[3] / "testdata"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"Generated {now.date()} — dates are relative, so regenerate if these age.\n")
    for vertical in verticals:
        cfg = get_vertical_config(vertical)
        content = build_csv(vertical, now, seed=args.seed)
        path = out_dir / f"{vertical}_customers.csv"
        path.write_text(content, encoding="utf-8")
        rows = content.count("\n") - 1
        customers = sum(c.count for c in COHORTS)
        print(f"{path.name}  —  {customers} customers, {rows} visit rows")
        print(
            f"  vertical '{vertical}': expected cadence {cfg.expected_interval_days:g}d, "
            f"attribution window {cfg.attribution_window_days}d"
        )
        for c in COHORTS:
            print(f"    {c.count:>2} × {c.label:<11} -> {c.expect:<10} {c.note}")
        print()

    print("Upload one through http://localhost:5173/setup (pick the matching vertical).")
    print("Each customer's LAST NAME is the cohort, so you can check intent against result.")


if __name__ == "__main__":
    main()
