import tempfile
import unittest
from pathlib import Path

from interview_terminology import InterviewTerminology, load_terminology


SAMPLE = """# 词典
| 标准术语 | 英文全称 | 常见别名或错词 | 准确定义 | 面试口述 |
|---|---|---|---|---|
| Skill | Skill | ski; SKI | 可复用能力模块 | 封装能力 |
| MCP | Model Context Protocol | mcp | 开放协议 | 连接工具 |
| Agent Workflow | Agent Workflow | agentworkflow | 智能体工作流 | 编排流程 |
"""


class InterviewTerminologyTests(unittest.TestCase):
    def _service(self, folder):
        path = Path(folder) / "terms.md"
        path.write_text(SAMPLE, encoding="utf-8")
        return InterviewTerminology(path)

    def test_loads_editable_markdown_table(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self._service(folder)
            self.assertEqual(len(service.terms), 3)
            self.assertEqual(load_terminology(service.path)[1]["canonical"], "MCP")

    def test_corrects_standalone_asr_terms_and_tracks_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self._service(folder).correct("ski 和 agentworkflow 怎么用？")
            self.assertEqual(result["corrected"], "Skill 和 Agent Workflow 怎么用？")
            self.assertEqual(len(result["changes"]), 2)
            self.assertTrue(result["risk"]["correction_applied"])

    def test_does_not_replace_alias_inside_normal_word(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self._service(folder).correct("skiing is a sport")
            self.assertEqual(result["corrected"], "skiing is a sport")

    def test_reports_known_and_unknown_acronyms(self):
        with tempfile.TemporaryDirectory() as folder:
            risk = self._service(folder).analyze("MCP 和 XYZ 有什么区别？")
            self.assertIn("MCP", risk["matched_terms"])
            self.assertEqual(risk["unknown_acronyms"], ["XYZ"])

    def test_correction_does_not_cascade_into_new_term(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self._service(folder)
            result = service.correct("agentworkflow")
            self.assertEqual(result["corrected"], "Agent Workflow")


if __name__ == "__main__":
    unittest.main()
