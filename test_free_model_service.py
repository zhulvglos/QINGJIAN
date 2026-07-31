import unittest
from datetime import datetime, timezone, timedelta

from free_model_service import (FREE_MODEL_DAILY_URL, effective_flash_date,
                                normalize_free_model_digest)
from news_service import NewsServiceError


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


if __name__ == "__main__":
    unittest.main()
