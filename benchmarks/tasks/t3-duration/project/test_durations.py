import unittest
from durations import parse_duration, format_duration


class ParseTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_duration('45s'), 45)
        self.assertEqual(parse_duration('2d'), 172800)

    def test_combined(self):
        self.assertEqual(parse_duration('1h30m'), 5400)
        self.assertEqual(parse_duration('1d2h3m4s'), 93784)

    def test_spaces(self):
        self.assertEqual(parse_duration('1h 30m'), 5400)

    def test_invalid(self):
        for bad in ['', 'abc', '10', '5x', 'h1']:
            with self.assertRaises(ValueError):
                parse_duration(bad)


class FormatTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_duration(5400), '1h30m')
        self.assertEqual(format_duration(0), '0s')
        self.assertEqual(format_duration(93784), '1d2h3m4s')


if __name__ == '__main__':
    unittest.main()
