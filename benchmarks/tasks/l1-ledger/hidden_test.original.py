import unittest
from decimal import Decimal

from ledger.cli import main
from ledger.models import Transaction
from ledger.parser import parse_csv
from ledger.rates import UnknownCurrency, convert
from ledger.report import category_totals, monthly_totals, total

HDR = "date,description,category,amount,currency\n"
D = Decimal


class Parser(unittest.TestCase):
    def test_default_and_empty_currency(self):
        rows = parse_csv(HDR + "2026-01-01,a,x,1,\n2026-01-02,b,x,2,gbp\n")
        self.assertEqual([r.currency for r in rows], ["USD", "GBP"])
        self.assertEqual(Transaction.__dataclass_fields__["currency"].default, "USD")

    def test_bad_currency_line_number(self):
        for bad in ("EU", "EURO", "E1R", "€€€"):
            with self.assertRaises(ValueError) as cm:
                parse_csv(HDR + "2026-01-01,a,x,1,USD\n2026-01-02,b,x,2,%s\n" % bad)
            self.assertEqual(str(cm.exception), "bad currency on line 3")

    def test_whitespace_around_currency_is_stripped(self):
        self.assertEqual(parse_csv(HDR + "2026-01-01,a,x,1, cad \n")[0].currency, "CAD")


class Rates(unittest.TestCase):
    def test_convert_rounding_half_up(self):
        self.assertEqual(convert(D("1.00"), "EUR", "USD", {"EUR": D("1.005")}), D("1.01"))
        self.assertEqual(convert(D("10"), "EUR", "USD", {"EUR": D("1.10")}), D("11.00"))

    def test_same_currency_is_unchanged(self):
        self.assertEqual(convert(D("1.234"), "USD", "USD", {}), D("1.234"))
        self.assertEqual(str(convert(D("1.234"), "EUR", "EUR", {"EUR": D("2")})), "1.234")

    def test_cross_rate_through_base(self):
        rates = {"EUR": D("1.10"), "GBP": D("1.25")}
        self.assertEqual(convert(D("100"), "EUR", "GBP", rates), D("88.00"))
        self.assertEqual(convert(D("100"), "USD", "GBP", rates), D("80.00"))
        self.assertEqual(convert(D("100"), "GBP", "USD", rates), D("125.00"))

    def test_unknown(self):
        with self.assertRaises(UnknownCurrency) as cm:
            convert(D("1"), "JPY", "USD", {})
        self.assertEqual(str(cm.exception), "JPY")
        self.assertTrue(issubclass(UnknownCurrency, ValueError))
        with self.assertRaises(UnknownCurrency) as cm:
            convert(D("1"), "USD", "CHF", {"EUR": D("1.1")})
        self.assertEqual(str(cm.exception), "CHF")
        with self.assertRaises(UnknownCurrency):
            convert(D("1"), "EUR", "USD", None)


class Reports(unittest.TestCase):
    TEXT = (HDR + "2026-01-05,a,food,10,EUR\n2026-01-06,b,,4,USD\n2026-02-01,c,food,2.50,USD\n"
            "2026-02-02,d,travel,12.50,USD\n2026-02-03,e,apps,12.50,USD\n")

    def test_total_and_monthly_with_conversion(self):
        rows = parse_csv(self.TEXT)
        rates = {"EUR": D("1.10")}
        self.assertEqual(total(rows, rates), D("42.50"))
        self.assertEqual(list(monthly_totals(rows, rates).items()), [("2026-01", D("15.00")), ("2026-02", D("27.50"))])

    def test_default_args_still_work_for_usd_only(self):
        rows = parse_csv(HDR + "2026-01-01,a,x,1.50,USD\n")
        self.assertEqual(total(rows), D("1.50"))
        self.assertEqual(monthly_totals(rows), {"2026-01": D("1.50")})

    def test_non_usd_without_rates_raises(self):
        with self.assertRaises(UnknownCurrency):
            total(parse_csv(self.TEXT))
        with self.assertRaises(UnknownCurrency):
            monthly_totals(parse_csv(self.TEXT))
        with self.assertRaises(UnknownCurrency):
            category_totals(parse_csv(self.TEXT))

    def test_category_order_and_uncategorized(self):
        rows = parse_csv(self.TEXT)
        got = category_totals(rows, {"EUR": D("1.10")})
        self.assertEqual(list(got.items()),
                         [("food", D("13.50")), ("apps", D("12.50")), ("travel", D("12.50")), ("uncategorized", D("4"))])

    def test_category_conversion_is_per_transaction(self):
        rows = parse_csv(HDR + "2026-01-01,a,x,0.01,EUR\n2026-01-02,b,x,0.01,EUR\n")
        self.assertEqual(category_totals(rows, {"EUR": D("1.50")}), {"x": D("0.04")})


class Cli(unittest.TestCase):
    TEXT = Reports.TEXT

    def test_default_output_unchanged_for_usd(self):
        self.assertEqual(main([], "date,description,category,amount\n2026-01-01,a,x,1\n"), (0, "2026-01: 1.00\nTOTAL: 1.00"))

    def test_monthly_with_rate(self):
        self.assertEqual(main(["--rate", "eur=1.10"], self.TEXT), (0, "2026-01: 15.00\n2026-02: 27.50\nTOTAL: 42.50"))

    def test_by_category(self):
        code, out = main(["--by-category", "--rate", "EUR=1.10"], self.TEXT)
        self.assertEqual((code, out), (0, "food: 13.50\napps: 12.50\ntravel: 12.50\nuncategorized: 4.00\nTOTAL: 42.50"))

    def test_base_currency_and_repeated_rates(self):
        code, out = main(["--base", "gbp", "--rate", "EUR=1.10", "--rate", "gbp=1.25", "--by-category"], self.TEXT)
        self.assertEqual(code, 0)
        self.assertEqual(out, "food: 10.80\napps: 10.00\ntravel: 10.00\nuncategorized: 3.20\nTOTAL: 34.00")

    def test_csv_format(self):
        code, out = main(["--format", "csv", "--rate", "EUR=1.10"], self.TEXT)
        self.assertEqual((code, out), (0, "month,amount\n2026-01,15.00\n2026-02,27.50\nTOTAL,42.50"))
        code, out = main(["--by-category", "--format", "csv", "--rate", "EUR=1.10"], self.TEXT)
        self.assertEqual(out, "category,amount\nfood,13.50\napps,12.50\ntravel,12.50\nuncategorized,4.00\nTOTAL,42.50")
        text = HDR + '2026-01-01,a,"big, fish",1,USD\n2026-01-02,b,say "hi",2,USD\n'
        self.assertEqual(main(["--by-category", "--format", "csv"], text),
                         (0, 'category,amount\nsay "hi",2.00\n"big, fish",1.00\nTOTAL,3.00'.replace('say "hi"', '"say ""hi"""')))
        self.assertEqual(main(["--format", "text"], HDR + "2026-01-01,a,x,1,USD\n"), (0, "2026-01: 1.00\nTOTAL: 1.00"))

    def test_errors(self):
        self.assertEqual(main(["--format", "CSV"], self.TEXT), (2, "error: bad format CSV"))
        self.assertEqual(main(["--format"], self.TEXT), (2, "error: missing value for --format"))
        self.assertEqual(main(["--nope"], self.TEXT), (2, "error: unexpected argument --nope"))
        self.assertEqual(main(["--rate"], self.TEXT), (2, "error: missing value for --rate"))
        self.assertEqual(main(["--base"], self.TEXT), (2, "error: missing value for --base"))
        for bad in ("EUR", "EUR=", "EUR=abc", "EUR=0", "EUR=-1", "=1.2", "EUR=NaN"):
            self.assertEqual(main(["--rate", bad], self.TEXT), (2, "error: bad rate " + bad))
        self.assertEqual(main([], self.TEXT), (2, "error: unknown currency EUR"))
        self.assertEqual(main(["--base", "chf", "--rate", "EUR=1.1"], self.TEXT), (2, "error: unknown currency CHF"))
        self.assertEqual(main([], HDR + "2026-01-01,a,x,1,EU\n"), (2, "error: bad currency on line 2"))
        self.assertEqual(main([], "date,description,category\n"), (2, "error: missing column: amount"))
        self.assertEqual(main([], "date,description,category,amount\nx,a,b,1\n"), (2, "error: bad row on line 2"))


if __name__ == "__main__":
    unittest.main()
