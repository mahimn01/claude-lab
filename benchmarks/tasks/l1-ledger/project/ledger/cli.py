from .parser import parse_csv
from .report import monthly_totals, total


def money(value):
    return "%.2f" % value


def main(argv, text):
    """Run the report. Returns (exit_code, output_text)."""
    if argv:
        return 2, "error: unexpected argument " + argv[0]
    try:
        transactions = parse_csv(text)
    except ValueError as exc:
        return 2, "error: " + str(exc)
    lines = ["%s: %s" % (month, money(amount)) for month, amount in monthly_totals(transactions).items()]
    lines.append("TOTAL: " + money(total(transactions)))
    return 0, "\n".join(lines)
