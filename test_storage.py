import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from main import StickyNotesApp
from calendar_service import HOLIDAYS_2026, lunar_month, month_grid
from storage import NoteStore, STEP_PLAN_BASE_URL, STEP_PLAN_MODEL


class NoteStoreTests(unittest.TestCase):
    def test_note_round_trip_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            store = NoteStore(path)
            note = store.new_note("测试便签", "内容", [
                {"start": "1.0", "end": "1.2", "style": "bold"}
            ])
            store.save()

            loaded = NoteStore(path)
            self.assertEqual(loaded.notes[0]["title"], "测试便签")
            self.assertEqual(loaded.notes[0]["content"], "内容")
            self.assertEqual(loaded.notes[0]["formats"][0]["style"], "bold")
            loaded.delete(note["id"])
            self.assertEqual(NoteStore(path).notes, [])

    def test_completed_task_archive_is_persistent_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            store = NoteStore(path)
            record = store.archive_completed_task(
                "sticky", "note-1", "项目计划", "☑ 完成需求评审\n会议纪要已同步")
            loaded = NoteStore(path)
            self.assertEqual(loaded.completed_tasks[0]["id"], record["id"])
            self.assertEqual(loaded.completed_tasks[0]["source_title"], "项目计划")
            self.assertEqual(loaded.completed_tasks[0]["content"], "☑ 完成需求评审\n会议纪要已同步")

    def test_legacy_completed_tasks_restore_without_duplicate_or_guessing_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            store = NoteStore(path)
            first = store.new_note("第一条", "☐ 整理纪要")
            second = store.new_note("第二条", "")
            second["id"] = "second-note"
            store.archive_completed_task("sticky", first["id"], first["title"], "☑ 整理纪要")
            store.archive_completed_task("sticky", first["id"], first["title"], "☑ 整理纪要")
            store.archive_completed_task("sticky", second["id"], second["title"], "☑ 整理纪要")
            result = store.recover_legacy_completed_tasks()
            self.assertEqual(result, {"restored": 0, "pending_review": 2})
            self.assertIn("☐ 整理纪要", first["content"])
            self.assertEqual(len(store.completed_tasks), 2)

    def test_mini_hermes_recovery_restores_confirmed_blocks_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            store = NoteStore(path)
            note = store.new_note("mini hermes", "☐ ocr图片：\n命令", kind="sticky")
            store.archive_completed_task("sticky", note["id"], note["title"], "☑ min问答：\n命令")
            self.assertEqual(store.recover_mini_hermes_content(), {"restored": 3})
            self.assertIn("☐ min问答：", note["content"])
            self.assertIn("☐ 正则清洗（快）：", note["content"])
            self.assertIn("☐ LLM 清洗（精准，需要网络）：", note["content"])
            self.assertEqual(store.completed_tasks, [])
            self.assertEqual(store.recover_mini_hermes_content(), {"restored": 0})

    def test_existing_notes_migrate_to_sticky_and_unified_reminder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({"notes": [{
                "id": "old-1", "title": "旧便签", "content": "内容",
                "reminder": "2099-01-01 09:00"
            }], "settings": {}}), encoding="utf-8")
            store = NoteStore(path)
            self.assertEqual(store.notes[0]["kind"], "sticky")
            self.assertEqual(store.reminders[0]["source_id"], "old-1")

    def test_legacy_modelscope_ai_config_migrates_to_step_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({"settings": {
                "ai_base_url": "https://example.api-inference.modelscope.cn/v1",
                "ai_model": "unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit",
            }}), encoding="utf-8")
            store = NoteStore(path)
            self.assertEqual(store.settings["ai_base_url"], STEP_PLAN_BASE_URL)
            self.assertEqual(store.settings["ai_model"], STEP_PLAN_MODEL)
            self.assertEqual(store.settings["ai_reasoning_effort"], "low")

    def test_existing_local_ai_config_migrates_to_separate_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({"settings": {
                "schema_version": 5,
                "ai_base_url": "http://127.0.0.1:8080/v1",
                "ai_model": "qwen3-8b-local",
                "ai_reasoning_effort": "high",
            }}), encoding="utf-8")
            store = NoteStore(path)
            self.assertEqual(store.settings["ai_provider_mode"], "llama_cpp")
            self.assertEqual(
                store.settings["ai_llama_cpp_base_url"],
                "http://127.0.0.1:8080/v1")
            self.assertEqual(store.settings["ai_llama_cpp_model"], "qwen3-8b-local")
            self.assertEqual(store.settings["ai_llama_cpp_reasoning_effort"], "high")
            self.assertEqual(store.settings["ai_step_plan_base_url"], STEP_PLAN_BASE_URL)
            self.assertEqual(store.settings["schema_version"], 7)
            self.assertEqual(store.settings["interview_answer_mode"], "hybrid")

    def test_invalid_interview_answer_mode_resets_to_hybrid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({"settings": {
                "interview_answer_mode": "invalid",
            }}), encoding="utf-8")
            self.assertEqual(NoteStore(path).settings["interview_answer_mode"], "hybrid")

    def test_source_reminder_due_snooze_and_recurring_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NoteStore(Path(directory) / "data.json")
            note = store.new_note("学习手记", "内容", kind="journal")
            past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
            reminder = store.set_source_reminder(note, past, "daily")
            self.assertEqual(store.due_reminders()[0]["status"], "notified")
            store.snooze_reminder(reminder["id"], 30)
            self.assertEqual(reminder["status"], "pending")
            reminder["remind_at"] = past
            store.complete_reminder(reminder["id"])
            self.assertEqual(reminder["status"], "pending")
            self.assertGreater(datetime.strptime(reminder["remind_at"], "%Y-%m-%d %H:%M"),
                               datetime.now())

    def test_categories_tags_and_learning_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NoteStore(Path(directory) / "data.json")
            note = store.new_note("Agent手记", "内容", kind="journal",
                                  category="AI", tags=["Agent", "产品"])
            store.remember_category("AI")
            today = datetime.now().date()
            store.log_learning(note["id"], (today - timedelta(days=1)).isoformat())
            store.log_learning(note["id"], today.isoformat())
            stats = store.learning_stats(note)
            self.assertEqual(note["category"], "AI")
            self.assertEqual(note["tags"], ["Agent", "产品"])
            self.assertEqual(stats["streak"], 2)

    def test_category_tags_and_scoped_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NoteStore(Path(directory) / "data.json")
            first = store.new_note("一", kind="journal", category="AI",
                                   tags=["Agent", "产品"])
            second = store.new_note("二", kind="journal", category="AI",
                                    tags=["Agent", "知识库"])
            other = store.new_note("三", kind="journal", category="工程",
                                   tags=["Agent"])
            self.assertEqual(store.tags_for_category("AI"), ["Agent", "产品", "知识库"])
            self.assertEqual(store.rename_tag("AI", "Agent", "智能体"), 2)
            self.assertIn("智能体", first["tags"])
            self.assertIn("智能体", second["tags"])
            self.assertEqual(other["tags"], ["Agent"])

    def test_categories_follow_actual_journal_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({
                "notes": [{
                    "id": "journal-1", "title": "面试录音", "content": "",
                    "kind": "journal", "category": "已挂", "tags": []
                }],
                "categories": ["每日学习", "未知"],
                "settings": {},
            }, ensure_ascii=False), encoding="utf-8")
            store = NoteStore(path)
            self.assertEqual(store.categories, ["已挂"])
            store.notes[0]["category"] = "产品经理"
            store.save()
            self.assertEqual(store.categories, ["产品经理"])
            store.delete("journal-1")
            self.assertEqual(store.categories, [])

    def test_advanced_recurrence_calculation(self):
        monthly = {"repeat": "monthly", "interval": 1}
        yearly = {"repeat": "yearly", "interval": 1}
        workday = {"repeat": "workday", "interval": 1}
        self.assertEqual(NoteStore._next_occurrence(
            datetime(2026, 1, 31, 9), monthly), datetime(2026, 2, 28, 9))
        self.assertEqual(NoteStore._next_occurrence(
            datetime(2024, 2, 29, 9), yearly), datetime(2025, 2, 28, 9))
        self.assertEqual(NoteStore._next_occurrence(
            datetime(2026, 7, 24, 9), workday).weekday(), 0)


class EdgeDetectionTests(unittest.TestCase):
    def setUp(self):
        self.app = StickyNotesApp.__new__(StickyNotesApp)

    def test_left_right_and_top_use_same_gap(self):
        self.assertEqual(self.app.detect_docked_edge(12, 100, 420, 1920), "left")
        self.assertEqual(self.app.detect_docked_edge(1488, 100, 420, 1920), "right")
        self.assertEqual(self.app.detect_docked_edge(100, 12, 420, 1920), "top")

    def test_window_away_from_edges_does_not_hide(self):
        self.assertIsNone(self.app.detect_docked_edge(100, 100, 420, 1920))


class CheckLabelTests(unittest.TestCase):
    def test_checked_and_unchecked_symbols(self):
        app = StickyNotesApp.__new__(StickyNotesApp)
        app.top_var = MockBoolean(True)
        app.edge_var = MockBoolean(False)
        app.top_label_var = MockString()
        app.edge_label_var = MockString()
        app.sync_check_labels()
        self.assertEqual(app.top_label_var.value, "✔ 置顶")
        self.assertEqual(app.edge_label_var.value, "□ 贴边隐藏")


class CalendarServiceTests(unittest.TestCase):
    def test_month_grid_has_six_complete_weeks(self):
        self.assertEqual(len(month_grid(2026, 7)), 42)

    def test_lunar_date_and_solar_term(self):
        info = lunar_month(2026, 7)["2026-07-23"]
        self.assertEqual((info["month"], info["day"]), (6, 10))
        self.assertEqual(info["solar_term"], "大暑")

    def test_official_2026_holiday_and_makeup_workday(self):
        self.assertEqual(HOLIDAYS_2026["2026-10-01"]["type"], "holiday")
        self.assertEqual(HOLIDAYS_2026["2026-10-10"]["type"], "workday")


class MockBoolean:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class MockString:
    def set(self, value):
        self.value = value


if __name__ == "__main__":
    unittest.main()
