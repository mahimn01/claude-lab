import unittest
from decimal import Decimal

from ledger.cli import main
from ledger.parser import parse_csv
from ledger.report import monthly_totals, total

CSV = """date,description,category,amount
2026-01-05,Coffee,food,3.50
2026-01-20,Train,travel,12.00
2026-02-02,Lunch,food,9.25
"""


class ExistingBehaviour(unittest.TestCase):
    def test_parse_and_total(self):
        rows = parse_csv(CSV)
        self.assertEqual(len(rows), 3)
        self.assertEqual(total(rows), Decimal("24.75"))

    def test_monthly(self):
        self.assertEqual(list(monthly_totals(parse_csv(CSV)).items()),
                         [("2026-01", Decimal("15.50")), ("2026-02", Decimal("9.25"))])

    def test_cli_default(self):
        self.assertEqual(main([], CSV), (0, "2026-01: 15.50\n2026-02: 9.25\nTOTAL: 24.75"))

    def test_bad_row(self):
        with self.assertRaises(ValueError):
            parse_csv("date,description,category,amount\nnope,x,y,1\n")


class MultiCurrency(unittest.TestCase):
    def test_currency_column_is_optional_and_defaults_to_usd(self):
        self.assertEqual(parse_csv(CSV)[0].currency, "USD")

    def test_currency_column_is_read_and_uppercased(self):
        rows = parse_csv("date,description,category,amount,currency\n2026-03-01,Taxi,travel,10,eur\n")
        self.assertEqual(rows[0].currency, "EUR")

    def test_by_category_with_rates(self):
        text = ("date,description,category,amount,currency\n"
                "2026-03-01,Taxi,travel,10,EUR\n"
                "2026-03-02,Lunch,food,5,USD\n")
        code, out = main(["--by-category", "--rate", "EUR=1.10"], text)
        self.assertEqual(code, 0)
        self.assertEqual(out, "travel: 11.00\nfood: 5.00\nTOTAL: 16.00")


if __name__ == "__main__":
    unittest.main()
