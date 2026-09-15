"""Generates a realistic month of fake Singapore transactions for demo purposes."""

import random
from datetime import date, timedelta

from src.db import get_session, init_db
from src.models import AgentAction, Transaction

# (merchant, typical amount range, lat, lng, location_name)
# Everyday merchants: drawn multiple times a day, amount varies each time.
DAILY_MERCHANTS = [
    ("NTUC FairPrice", (15, 90), 1.3521, 103.8198, "Toa Payoh"),
    ("Cold Storage", (20, 100), 1.3048, 103.8318, "Orchard"),
    ("Grab Food - Ya Kun", (5, 15), 1.2966, 103.8520, "Marina Bay"),
    ("Din Tai Fung", (18, 60), 1.3000, 103.8380, "Somerset"),
    ("Koufu Food Court", (6, 14), 1.3331, 103.7767, "Clementi"),
    ("Grab - Ride", (6, 25), 1.3151, 103.7649, "Jurong East"),
    ("SMRT EZ-Link Top-up", (10, 50), 1.3644, 103.9915, "Tampines"),
    ("Shopee", (10, 150), 1.2830, 103.8600, "Bugis"),
    ("Uniqlo", (20, 120), 1.3006, 103.8368, "Orchard Road"),
]

# Recurring merchants: charged exactly once a month, fixed amount.
RECURRING_MERCHANTS = [
    ("Netflix", (16.98, 16.98), 1.29, 103.85, "Online"),
    ("Spotify", (11.98, 11.98), 1.29, 103.85, "Online"),
    ("Singtel Bill", (45, 90), 1.29, 103.85, "Online"),
    ("SP Group Electricity", (60, 150), 1.29, 103.85, "Online"),
    ("Anytime Fitness", (89, 89), 1.3138, 103.8159, "Novena"),
]

# Occasional, low-frequency merchant (appears a handful of times a month, not daily).
OCCASIONAL_MERCHANTS = [
    ("Guardian Pharmacy", (8, 40), 1.3048, 103.8318, "Orchard"),
]

SALARY = ("Salary - KLP LLP", (2200, 2200), 1.28, 103.85, "Raffles Place")

# Extra recurring subscriptions injected once, on top of the normal set, to
# create genuine subscription-creep for the AI agent to catch.
SUBSCRIPTION_CREEP = [
    ("Disney+ Hotstar", (11.98, 11.98), 1.29, 103.85, "Online"),
    ("Adobe Creative Cloud", (32.88, 32.88), 1.29, 103.85, "Online"),
]


def _make_txn(merchant, txn_date, amount_sign, rng) -> Transaction:
    name, (lo, hi), lat, lng, location = merchant
    amount = round(rng.uniform(lo, hi), 2) * amount_sign
    return Transaction(
        date=txn_date,
        description=name,
        merchant=name,
        amount=amount,
        source="synthetic",
        lat=lat + rng.uniform(-0.01, 0.01),
        lng=lng + rng.uniform(-0.01, 0.01),
        location_name=location,
    )


def generate_month(session, year: int, month: int, seed: int = 42) -> int:
    """Populate one synthetic month of transactions. Returns count created.

    Category is deliberately left unset — a real bank statement never comes with
    categories attached, that's the AI agent's job (src/agent.py). These
    transactions are inserted "raw", same as a real CSV import would be.
    """
    rng = random.Random(seed)
    start = date(year, month, 1)
    days_in_month = 28 if month == 2 else 30
    count = 0

    # Salary, once a month.
    txn = _make_txn(SALARY, date(year, month, 25), amount_sign=1, rng=rng)
    session.add(txn)
    count += 1

    # Recurring bills/subscriptions: exactly once a month, on a random day each.
    for merchant in RECURRING_MERCHANTS:
        txn_date = start + timedelta(days=rng.randint(0, days_in_month - 1))
        txn = _make_txn(merchant, txn_date, amount_sign=-1, rng=rng)
        session.add(txn)
        count += 1

    # Occasional merchants: 2-4 times across the month, spaced out.
    for merchant in OCCASIONAL_MERCHANTS:
        for _ in range(rng.randint(2, 4)):
            txn_date = start + timedelta(days=rng.randint(0, days_in_month - 1))
            txn = _make_txn(merchant, txn_date, amount_sign=-1, rng=rng)
            session.add(txn)
            count += 1

    # Everyday spending: 2-4 transactions per day from the daily merchant pool.
    for day_offset in range(days_in_month):
        txn_date = start + timedelta(days=day_offset)
        for _ in range(rng.randint(2, 4)):
            merchant = rng.choice(DAILY_MERCHANTS)
            txn = _make_txn(merchant, txn_date, amount_sign=-1, rng=rng)
            session.add(txn)
            count += 1

    # Inject genuine subscription creep: extra recurring services on top of the normal set.
    for creep in rng.sample(SUBSCRIPTION_CREEP, k=rng.randint(1, 2)):
        txn_date = start + timedelta(days=rng.randint(0, days_in_month - 1))
        txn = _make_txn(creep, txn_date, amount_sign=-1, rng=rng)
        session.add(txn)
        count += 1

    session.add(
        AgentAction(
            action_type="import",
            summary=f"Generated {count} synthetic transactions for {year}-{month:02d}",
            reasoning="Demo data generator — not a real statement import.",
        )
    )
    session.commit()
    return count


if __name__ == "__main__":
    init_db()
    session = get_session()
    n = generate_month(session, 2026, 9)
    print(f"Created {n} synthetic transactions for 2026-09")
    session.close()
