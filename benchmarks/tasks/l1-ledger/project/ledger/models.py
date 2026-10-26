from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Transaction:
    day: date
    description: str
    category: str
    amount: Decimal
