from collections import defaultdict
from decimal import Decimal


def total(transactions):
    return sum((t.amount for t in transactions), Decimal("0"))


def monthly_totals(transactions):
    """Return {'YYYY-MM': Decimal} in chronological order."""
    sums = defaultdict(Decimal)
    for t in transactions:
        sums[t.day.strftime("%Y-%m")] += t.amount
    return dict(sorted(sums.items()))
