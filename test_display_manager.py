import unittest

from display_manager import (DisplayArea, detect_docked_edge, display_for_bounds,
                             ensure_visible_position, hidden_position,
                             revealed_position)


LEFT = DisplayArea(1, -1920, 0, 0, 1080, -1920, 0, 0, 1040)
MAIN = DisplayArea(2, 0, 0, 1920, 1080, 0, 0, 1920, 1040, True)


class DisplayGeometryTests(unittest.TestCase):
    def test_selects_left_display_for_negative_coordinates(self):
        self.assertEqual(display_for_bounds((-1600, 100, 420, 620), [LEFT, MAIN]), LEFT)

    def test_detects_each_edge_in_current_display_work_area(self):
        self.assertEqual(detect_docked_edge((-1920, 100, 420, 620), LEFT, 12), "left")
        self.assertEqual(detect_docked_edge((-420, 100, 420, 620), LEFT, 12), "right")
        self.assertEqual(detect_docked_edge((-1000, 0, 420, 620), LEFT, 12), "top")

    def test_hide_and_reveal_keep_negative_display_coordinates(self):
        bounds = (-1920, 100, 420, 620)
        hidden = hidden_position("left", bounds, LEFT, 7)
        self.assertEqual(hidden, (-2333, 100))
        revealed = revealed_position("left", (hidden[0], hidden[1], 420, 620), LEFT)
        self.assertEqual(revealed, (-1920, 100))

    def test_removed_display_moves_window_to_remaining_work_area(self):
        self.assertEqual(ensure_visible_position((-1600, 100, 420, 620), [MAIN]), (0, 100))

    def test_tiny_remaining_sliver_is_recovered(self):
        self.assertEqual(ensure_visible_position((1900, 100, 420, 620), [MAIN]), (1500, 100))


if __name__ == "__main__":
    unittest.main()
