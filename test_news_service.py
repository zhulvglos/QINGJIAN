import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_service import (NewsServiceError, effective_daily_date, load_daily_cache,
                          normalize_daily, save_daily_cache)


class NewsServiceTests(unittest.TestCase):
    def test_normalize_daily_flattens_sections(self):
        result = normalize_daily({
            "date": "2026-07-24",
            "attribution": {"source": "AI HOT", "canonical": "https://example.test/daily"},
            "sections": [{
                "label": "模型发布/更新",
                "items": [{
                    "title": "示例新闻",
                    "summary": "示例摘要",
                    "sourceName": "示例来源",
                    "sourceUrl": "https://example.test/source",
                    "permalink": "https://example.test/item",
                }],
            }],
        })
        self.assertEqual(result["date"], "2026-07-24")
        self.assertEqual(result["items"][0]["category"], "模型发布/更新")
        self.assertEqual(result["items"][0]["title"], "示例新闻")

    def test_normalize_daily_rejects_empty_daily(self):
        with self.assertRaises(NewsServiceError):
            normalize_daily({"date": "2026-07-24", "sections": []})

    def test_daily_cache_round_trip(self):
        payload = {
            "date": "2026-07-24",
            "canonical": "https://example.test/daily",
            "items": [{"title": "本地缓存新闻"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news_cache.json"
            save_daily_cache(path, payload)
            self.assertEqual(load_daily_cache(path), payload)

    def test_invalid_daily_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news_cache.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertIsNone(load_daily_cache(path))

    def test_daily_date_stays_on_yesterday_before_eight(self):
        self.assertEqual(effective_daily_date(datetime(2026, 7, 25, 7, 59)),
                         "2026-07-24")

    def test_daily_date_switches_at_eight(self):
        self.assertEqual(effective_daily_date(datetime(2026, 7, 25, 8, 0)),
                         "2026-07-25")

    def test_daily_date_converts_aware_time_to_beijing(self):
        utc = timezone.utc
        self.assertEqual(effective_daily_date(datetime(2026, 7, 25, 0, 0, tzinfo=utc)),
                         "2026-07-25")
        self.assertEqual(effective_daily_date(
            datetime(2026, 7, 24, 23, 59, tzinfo=utc)), "2026-07-24")


if __name__ == "__main__":
    unittest.main()
