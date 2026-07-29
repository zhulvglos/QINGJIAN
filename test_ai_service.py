import json
import threading
import unittest
from unittest.mock import patch

from ai_service import (AIServiceError, MEETING_TASKS, REASONING_EFFORTS,
                        STEP_PLAN_MODELS, ai_provider, analyze_meeting,
                        answer_interview_question, chat_url,
                        chunk_interview_text, parse_sse_lines,
                        stream_chat_completion, strip_thinking)


class AIServiceTests(unittest.TestCase):
    def test_step_plan_provider_and_catalog(self):
        self.assertEqual(
            ai_provider("https://api.stepfun.com/step_plan/v1"), "step_plan")
        self.assertEqual(ai_provider("https://example.test/v1"), "custom")
        self.assertEqual(
            list(STEP_PLAN_MODELS),
            ["step-3.7-flash", "step-3.5-flash-2603", "step-3.5-flash"])
        self.assertEqual(list(REASONING_EFFORTS), ["low", "medium", "high"])

    def test_chat_url_accepts_base_or_full_path(self):
        self.assertEqual(chat_url("https://example.test/v1"),
                         "https://example.test/v1/chat/completions")
        full = "https://example.test/v1/chat/completions"
        self.assertEqual(chat_url(full), full)

    def test_strip_thinking_keeps_only_final_answer(self):
        self.assertEqual(strip_thinking("<think>内部推理</think>最终摘要"), "最终摘要")

    def test_parse_streamed_openai_chunks(self):
        lines = [
            ("data: " + json.dumps({"choices": [{"delta": {"content": "面试"}}]})).encode(),
            ("data: " + json.dumps({"choices": [{"delta": {"content": "摘要"}}]})).encode(),
            b"data: [DONE]",
        ]
        self.assertEqual(parse_sse_lines(lines), "面试摘要")

    def test_stream_callback_receives_visible_deltas_in_order(self):
        lines = [
            ("data: " + json.dumps({"choices": [{"delta": {"content": "先说结论"}}]})).encode(),
            ("data: " + json.dumps({"choices": [{"delta": {"content": "，再解释原因"}}]})).encode(),
            b"data: [DONE]",
        ]
        deltas = []
        result = parse_sse_lines(lines, on_delta=deltas.append)
        self.assertEqual(result, "先说结论，再解释原因")
        self.assertEqual("".join(deltas), result)

    def test_stream_can_be_cancelled(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(AIServiceError):
            parse_sse_lines([b"data: {}"], cancelled)

    def test_long_interview_is_split_without_loss(self):
        text = "说话人1：" + "甲" * 80 + "\n说话人2：" + "乙" * 80
        chunks = chunk_interview_text(text, max_chars=100)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))

    def test_completion_uses_mock_stream_and_removes_thinking(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                text = "<think>推理内容</think>最终面试摘要"
                payload = json.dumps({"choices": [{"delta": {"content": text}}]})
                return iter([f"data: {payload}\n".encode(), b"data: [DONE]\n"])

        config = {"base_url": "https://example.test/v1", "model": "test-model",
                  "api_key": "test-token", "timeout": 1}
        with patch("ai_service.urlopen", return_value=FakeResponse()):
            result = stream_chat_completion(
                config, [{"role": "user", "content": "测试"}], max_tokens=128)
        self.assertEqual(result, "最终面试摘要")

    def test_step_plan_request_uses_low_reasoning_effort(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                payload = json.dumps({"choices": [{"delta": {"content": "完成"}}]})
                return iter([f"data: {payload}\n".encode(), b"data: [DONE]\n"])

        config = {
            "base_url": "https://api.stepfun.com/step_plan/v1",
            "model": "step-3.5-flash",
            "reasoning_effort": "low",
            "api_key": "test-key",
        }
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("ai_service.urlopen", side_effect=fake_urlopen):
            self.assertEqual(stream_chat_completion(
                config, [{"role": "user", "content": "测试"}], max_tokens=64), "完成")
        self.assertEqual(
            captured["url"],
            "https://api.stepfun.com/step_plan/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "step-3.5-flash")
        self.assertEqual(captured["body"]["reasoning_effort"], "low")

    def test_empty_final_answer_retries_without_token_cap(self):
        class FakeResponse:
            def __init__(self, lines):
                self.lines = lines

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter(self.lines)

        reasoning = json.dumps({"choices": [{
            "delta": {"reasoning_content": "内部分析"}, "finish_reason": "length"}]})
        answer = json.dumps({"choices": [{"delta": {"content": "最终答案"}}]})
        responses = [FakeResponse([f"data: {reasoning}\n".encode(), b"data: [DONE]\n"]),
                     FakeResponse([f"data: {answer}\n".encode(), b"data: [DONE]\n"])]
        bodies = []

        def fake_urlopen(request, timeout):
            bodies.append(json.loads(request.data.decode("utf-8")))
            return responses.pop(0)

        config = {"base_url": "https://example.test/v1", "model": "test-model",
                  "api_key": "test-token"}
        with patch("ai_service.urlopen", side_effect=fake_urlopen):
            result = stream_chat_completion(
                config, [{"role": "user", "content": "问题"}],
                max_tokens=None, retry_empty=True)
        self.assertEqual(result, "最终答案")
        self.assertEqual(len(bodies), 2)
        self.assertNotIn("max_tokens", bodies[0])
        self.assertIn("立即直接输出", bodies[1]["messages"][-1]["content"])

    def test_meeting_minutes_template_requires_actions_and_no_fabrication(self):
        instruction = MEETING_TASKS["minutes"][1]
        self.assertIn("行动项表格", instruction)
        self.assertIn("待确认", instruction)
        self.assertIn("不得补写", instruction)

    def test_meeting_analysis_uses_meeting_guardrails(self):
        config = {"base_url": "https://example.test/v1", "model": "test-model",
                  "api_key": "test-token"}
        with patch("ai_service.stream_chat_completion", return_value="会议纪要") as mocked:
            result = analyze_meeting("minutes", "会议方1：确定下周评审。", config)
        self.assertEqual(result, "会议纪要")
        messages = mocked.call_args.args[1]
        self.assertIn("不得编造", messages[0]["content"])
        self.assertIn("会议转写稿", messages[1]["content"])

    def test_live_question_answer_is_direct_without_fixed_template(self):
        config = {"base_url": "https://example.test/v1", "model": "test-model",
                  "api_key": "test-token"}
        with patch("ai_service.stream_chat_completion", return_value="直接答案") as mocked:
            result = answer_interview_question(
                "恐龙什么时候灭绝？", "刚才在讨论恐龙", "", config)
        self.assertEqual(result, "直接答案")
        messages = mocked.call_args.args[1]
        prompt = messages[1]["content"]
        self.assertIn("只输出一段自然、简洁", prompt)
        self.assertIn("100至250个汉字", prompt)
        self.assertIn("一般知识和技术问题", prompt)
        self.assertNotIn("先给出30至60秒", prompt)
        self.assertIsNone(mocked.call_args.kwargs["max_tokens"])
        self.assertTrue(mocked.call_args.kwargs["retry_empty"])


if __name__ == "__main__":
    unittest.main()
