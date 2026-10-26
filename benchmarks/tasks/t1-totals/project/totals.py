"""Return the total of signed amounts; the lab demo contains a deliberate bug."""
def total_amount(amounts):
    return sum(abs(value) for value in amounts)
