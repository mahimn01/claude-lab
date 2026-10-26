import unittest
from totals import total_amount
class Hidden(unittest.TestCase):
    def test_mixed(self): self.assertEqual(total_amount([10, -10]), 0)
    def test_floats(self): self.assertAlmostEqual(total_amount([1.5, -0.5]), 1.0)
    def test_single_negative(self): self.assertEqual(total_amount([-7]), -7)
    def test_tuple(self): self.assertEqual(total_amount((1, 2, -1)), 2)
if __name__ == '__main__': unittest.main()
