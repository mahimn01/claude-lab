import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from .models import Transaction

REQUIRED = ("date", "description", "category", "amount")


def parse_csv(text):
    """Parse CSV text with a header row into a list of Transaction objects.

    Raises ValueError("bad row on line N") for a row with a bad date or amount.
    Line numbers count the header as line 1.
    """
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError("missing column: " + missing[0])
    out = []
    for n, row in enumerate(reader, start=2):
        try:
            day = date.fromisoformat(row["date"].strip())
            amount = Decimal(row["amount"].strip())
        except (ValueError, InvalidOperation):
            raise ValueError("bad row on line %d" % n)
        out.append(Transaction(day, row["description"].strip(), row["category"].strip(), amount))
    return out
