import unittest
from textutil import slugify, truncate


class SlugTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify('Hello World'), 'hello-world')

    def test_punctuation_runs(self):
        self.assertEqual(slugify('Hello,   World!!'), 'hello-world')

    def test_trim(self):
        self.assertEqual(slugify('  --Hi there--  '), 'hi-there')


class TruncateTest(unittest.TestCase):
    def test_short(self):
        self.assertEqual(truncate('abc', 5), 'abc')

    def test_cut(self):
        self.assertEqual(len(truncate('abcdefghij', 6)), 6)
        self.assertTrue(truncate('abcdefghij', 6).endswith('...'))


if __name__ == '__main__':
    unittest.main()
