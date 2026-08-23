import unittest

from main import StickyNotesApp


class TaskChecklistTests(unittest.TestCase):
    def test_plain_line_becomes_pending_task(self):
        self.assertEqual(StickyNotesApp.toggled_task_line("整理会议纪要"),
                         "☐ 整理会议纪要")

    def test_pending_task_becomes_completed(self):
        self.assertEqual(StickyNotesApp.toggled_task_line("☐ 整理会议纪要"),
                         "☑ 整理会议纪要")

    def test_completed_task_becomes_pending(self):
        self.assertEqual(StickyNotesApp.toggled_task_line("☑ 整理会议纪要"),
                         "☐ 整理会议纪要")

    def test_completed_task_block_is_removed_from_source_content(self):
        content = "☐ 保留任务\n说明\n☑ 已完成任务\n补充说明\n☐ 后续任务"
        remaining, completed = StickyNotesApp.split_completed_task_blocks(content)
        self.assertEqual(remaining, "☐ 保留任务\n说明\n☐ 后续任务")
        self.assertEqual(completed, ["☑ 已完成任务\n补充说明"])


if __name__ == "__main__":
    unittest.main()
