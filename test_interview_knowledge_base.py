import tempfile
import unittest
from pathlib import Path

from interview_knowledge_base import InterviewKnowledgeBase, chunk_document, tokenize


class InterviewKnowledgeBaseTests(unittest.TestCase):
    def test_chinese_tokenizer_keeps_characters_and_bigrams(self):
        tokens = tokenize("北极星指标 AI Agent")
        self.assertIn("北极", tokens)
        self.assertIn("指标", tokens)
        self.assertIn("ai", tokens)

    def test_search_returns_relevant_source_and_writes_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "面试知识库"
            root.mkdir()
            (root / "指标方案.md").write_text(
                "# 北极星指标\n\n北极星指标选择有效看护事件完成率。", encoding="utf-8")
            (root / "项目介绍.md").write_text(
                "# 项目介绍\n\n这是一个智能婴儿床项目。", encoding="utf-8")
            cache = Path(directory) / "cache.json"
            knowledge = InterviewKnowledgeBase(root, cache)
            result = knowledge.search("你如何确定北极星指标？")
            self.assertEqual(result.sources[0], "指标方案.md")
            self.assertIn("有效看护事件完成率", result.context)
            self.assertTrue(cache.exists())

    def test_empty_or_unrelated_query_has_no_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "面试知识库"
            root.mkdir()
            (root / "项目.md").write_text("婴儿床看护", encoding="utf-8")
            knowledge = InterviewKnowledgeBase(root, Path(directory) / "cache.json")
            self.assertEqual(knowledge.search("历代皇帝").sources, [])

    def test_single_chinese_character_overlap_is_not_a_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "面试知识库"
            root.mkdir()
            (root / "方案.md").write_text("现代产品的多代版本规划", encoding="utf-8")
            knowledge = InterviewKnowledgeBase(root, Path(directory) / "cache.json")
            self.assertEqual(knowledge.search("请细数历代皇帝").sources, [])

    def test_long_document_is_chunked_without_dropping_text(self):
        text = "# 标题\n\n" + "甲" * 1200
        chunks = list(chunk_document(text, max_chars=500))
        self.assertGreaterEqual(len(chunks), 3)
        self.assertIn("甲" * 100, "".join(item["text"] for item in chunks))


if __name__ == "__main__":
    unittest.main()
