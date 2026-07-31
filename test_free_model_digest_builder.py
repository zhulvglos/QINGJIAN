import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.build_free_model_digest import openrouter_items


class FreeModelDigestBuilderTests(unittest.TestCase):
    @patch("scripts.build_free_model_digest.get_json")
    def test_only_keeps_zero_price_online_api(self, get_json):
        get_json.return_value = {"data": [
            {"id": "demo/reasoner:free", "name": "Reasoner Free",
             "description": "A reasoning model", "context_length": 128000,
             "pricing": {"prompt": "0", "completion": "0"},
             "architecture": {"input_modalities": ["text"]}},
            {"id": "demo/paid", "name": "Paid",
             "pricing": {"prompt": "0.1", "completion": "0.2"},
             "architecture": {"input_modalities": ["text"]}},
        ]}
        items = openrouter_items(datetime(2026, 7, 31, tzinfo=timezone.utc))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["access_type"], "在线 API")
        self.assertIn("未公布截止日期", items[0]["expires_at"])
        self.assertTrue(items[0]["features"])
        self.assertTrue(items[0]["use_cases"])

    @patch("scripts.build_free_model_digest.get_json")
    def test_detects_online_vision_model(self, get_json):
        get_json.return_value = {"data": [{
            "id": "demo/vision:free", "name": "Vision Free",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text", "image"]},
        }]}
        item = openrouter_items(datetime.now(timezone.utc))[0]
        self.assertEqual(item["category"], "VLM")
        self.assertIn("图片", item["features"])


if __name__ == "__main__":
    unittest.main()
