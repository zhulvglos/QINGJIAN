import unittest

from main import cyclic_index


class TitleNavigationTests(unittest.TestCase):
    def test_moves_within_current_list(self):
        self.assertEqual(cyclic_index(4, 1, 1), 2)
        self.assertEqual(cyclic_index(4, 2, -1), 1)

    def test_wraps_at_both_ends(self):
        self.assertEqual(cyclic_index(4, 3, 1), 0)
        self.assertEqual(cyclic_index(4, 0, -1), 3)

    def test_missing_selection_uses_directional_end(self):
        self.assertEqual(cyclic_index(4, None, 1), 0)
        self.assertEqual(cyclic_index(4, None, -1), 3)

    def test_empty_list_has_no_target(self):
        self.assertIsNone(cyclic_index(0, None, 1))


if __name__ == "__main__":
    unittest.main()
