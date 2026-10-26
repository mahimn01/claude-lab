import unittest
from totals import total_amount

class TotalsTest(unittest.TestCase):
    def test_refund_reduces_total(self):
        self.assertEqual(total_amount([20, -5, 3]), 18)

    def test_empty(self):
        self.assertEqual(total_amount([]), 0)

    def test_all_refunds(self):
        self.assertEqual(total_amount([-2, -3]), -5)

if __name__ == '__main__':
    unittest.main()
