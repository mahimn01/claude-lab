import unittest
from durations import parse_duration, format_duration
class Hidden(unittest.TestCase):
    def test_roundtrip(self):
        for s in [1, 59, 60, 61, 3600, 3661, 86400, 90061]:
            self.assertEqual(parse_duration(format_duration(s)), s)
    def test_format_exact(self):
        self.assertEqual(format_duration(60), '1m'); self.assertEqual(format_duration(86400), '1d')
    def test_upper_invalid(self):
        with self.assertRaises(ValueError): parse_duration('1H')
    def test_zero(self): self.assertEqual(parse_duration('0s'), 0)
    def test_trailing_garbage(self):
        with self.assertRaises(ValueError): parse_duration('1h30')
if __name__ == '__main__': unittest.main()
