import unittest
from datetime import datetime, timezone, timedelta

from free_model_service import (FREE_MODEL_DAILY_URL, effective_flash_date,
                                normalize_free_model_digest)
from news_service import NewsServiceError
from main import StickyNotesApp


class FreeModelServiceTests(unittest.TestCase):
    def test_digest_uses_non_redirecting_raw_url(self):
        self.assertEqual(
            FREE_MODEL_DAILY_URL,
            "https://raw.githubusercontent.com/zhulvglos/QINGJIAN/daily-data/daily.json")

    def test_business_date_changes_at_nine_beijing(self):
        tz = timezone(timedelta(hours=8))
        self.assertEqual(effective_flash_date(datetime(2026, 7, 31, 8, 59, tzinfo=tz)),
                         "2026-07-30")
        self.assertEqual(effective_flash_date(datetime(2026, 7, 31, 9, 0, tzinfo=tz)),
                         "2026-07-31")

    def test_normalize_preserves_model_metadata(self):
        result = normalize_free_model_digest({
            "date": "2026-07-31", "items": [{
                "title": "示例模型", "category": "LLM", "model_id": "demo/model",
                "free_type": "当前免费 API", "source_url": "https://example.com/model"}]})
        self.assertEqual(result["items"][0]["model_id"], "demo/model")
        self.assertEqual(result["items"][0]["permalink"], "https://example.com/model")

    def test_rejects_empty_digest(self):
        with self.assertRaises(NewsServiceError):
            normalize_free_model_digest({"date": "2026-07-31", "items": []})

    def test_old_cache_without_summaries_is_incomplete(self):
        payload = {"items": [{"title": "旧条目", "features": "", "use_cases": ""}]}
        self.assertFalse(StickyNotesApp.flash_cache_complete(payload))

    def test_cache_with_source_summaries_is_complete(self):
        payload = {"items": [{
            "title": "新条目", "features": "模型特点总结。", "use_cases": "适合代码审查。"}]}
        self.assertTrue(StickyNotesApp.flash_cache_complete(payload))

    def test_switching_news_tab_only_changes_selected_state(self):
        class FakeButton:
            def __init__(self):
                self.states = []

            def state(self, values):
                self.states.append(values)

        app = StickyNotesApp.__new__(StickyNotesApp)
        app.news_daily_tab = FakeButton()
        app.news_flash_tab = FakeButton()
        app.news_mode = "flash"
        app.update_news_tabs()
        self.assertEqual(app.news_daily_tab.states[-1], ["!selected"])
        self.assertEqual(app.news_flash_tab.states[-1], ["selected"])
        app.news_mode = "daily"
        app.update_news_tabs()
        self.assertEqual(app.news_daily_tab.states[-1], ["selected"])
        self.assertEqual(app.news_flash_tab.states[-1], ["!selected"])

    def test_news_layout_hides_all_non_news_controls(self):
        class FakeWidget:
            def __init__(self):
                self.hidden = 0

            def pack_forget(self):
                self.hidden += 1

        app = StickyNotesApp.__new__(StickyNotesApp)
        app.current_section = "news"
        names = ("title_entry", "reminder_actions",
                 "note_filter_frame", "ai_interview_frame")
        widgets = []
        for name in names:
            widget = FakeWidget()
            setattr(app, name, widget)
            widgets.append(widget)
        calls = []
        app.show_news_title = calls.append
        app.enforce_news_clean_layout()
        self.assertTrue(all(widget.hidden == 1 for widget in widgets))
        self.assertEqual(calls, [True])

    def test_non_news_layout_is_not_changed(self):
        app = StickyNotesApp.__new__(StickyNotesApp)
        app.current_section = "journal"
        app.enforce_news_clean_layout()


if __name__ == "__main__":
    unittest.main()
