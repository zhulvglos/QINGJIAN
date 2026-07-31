import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.build_free_model_digest import openrouter_items


class FreeModelDigestBuilderTests(unittest.TestCase):
    @patch("scripts.build_free_model_digest.get_json")
    def test_only_keeps_zero_price_online_api(self, get_json):
        get_json.return_value = {"data": [
            {"id": "demo/reasoner:free", "name": "Reasoner Free",
             "description": "A reasoning model designed for complex mathematics and logical analysis tasks.",
             "context_length": 128000,
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
            "description": "A multimodal vision model designed to understand images, charts and documents.",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text", "image"]},
        }]}
        item = openrouter_items(datetime.now(timezone.utc))[0]
        self.assertEqual(item["category"], "VLM")
        self.assertIn("图片", item["features"])

    @patch("scripts.build_free_model_digest.get_json")
    def test_summarizes_cohere_source_description_in_chinese(self, get_json):
        get_json.return_value = {"data": [{
            "id": "cohere/north-mini-code:free", "name": "Cohere: North Mini Code (free)",
            "description": ("North Mini Code is Cohere's first agentic coding model and the debut "
                            "of its North family. A sparse mixture-of-experts model with 30B total "
                            "parameters and 3B active, it is optimized for software engineering."),
            "context_length": 256000,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},
        }]}
        item = openrouter_items(datetime.now(timezone.utc))[0]
        self.assertIn("编程智能体", item["features"])
        self.assertIn("混合专家", item["features"])
        self.assertIn("30B", item["features"])
        self.assertIn("仓库级代码理解", item["use_cases"])
        self.assertNotIn("请查看来源页", item["features"] + item["use_cases"])

    @patch("scripts.build_free_model_digest.get_json")
    def test_drops_models_without_enough_source_information(self, get_json):
        get_json.return_value = {"data": [{
            "id": "demo/unknown:free", "name": "Unknown", "description": "Short",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},
        }]}
        self.assertEqual(openrouter_items(datetime.now(timezone.utc)), [])


if __name__ == "__main__":
    unittest.main()
