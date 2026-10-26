import unittest
from textutil import slugify, truncate
class Hidden(unittest.TestCase):
    def test_digits(self): self.assertEqual(slugify('Version 2.0 Release'), 'version-2-0-release')
    def test_empty(self): self.assertEqual(slugify(''), '')
    def test_only_punct(self): self.assertEqual(slugify('!!!'), '')
    def test_underscore(self): self.assertEqual(slugify('a_b  c'), 'a-b-c')
    def test_truncate_exact(self): self.assertEqual(truncate('abcdef', 6), 'abcdef')
    def test_truncate_tiny(self): self.assertEqual(truncate('abcdefgh', 3), '...')
if __name__ == '__main__': unittest.main()
