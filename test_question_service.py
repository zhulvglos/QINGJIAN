import unittest

from question_service import (InterviewQuestionDetector, extract_questions,
                              normalize_question, question_score)


class QuestionServiceTests(unittest.TestCase):
    def test_detects_direct_and_indirect_interview_questions(self):
        text = "请介绍一下你负责的项目。你在里面具体负责哪一部分？"
        questions = extract_questions(text)
        self.assertEqual(len(questions), 2)
        self.assertIn("介绍一下", questions[0]["question"])
        self.assertIn("负责哪一部分", questions[1]["question"])

    def test_plain_statement_is_not_question(self):
        self.assertEqual(extract_questions("我们下周继续讨论这个项目。"), [])
        self.assertLess(question_score("这是一个普通陈述。"), 0.48)

    def test_detector_deduplicates_and_keeps_context(self):
        detector = InterviewQuestionDetector()
        detector.add_utterance("我看到你做过一个空间配置项目。")
        result = detector.add_utterance("你具体负责哪一部分？")
        self.assertIn("空间配置项目", result["context"])
        self.assertIsNone(detector.add_utterance("你具体负责哪一部分？"))

    def test_normalizes_question_mark(self):
        self.assertEqual(normalize_question(" 为什么这么做。 "), "为什么这么做？")

    def test_detector_keeps_longer_context_and_removes_audio_overlap(self):
        detector = InterviewQuestionDetector(context_size=10)
        detector.add_utterance("我们先比较现有监护器和智能摇篮产品")
        result = detector.add_utterance("智能摇篮产品，那么你们的核心差异是什么？")
        self.assertIn("比较现有监护器", result["context"])
        self.assertEqual(result["context"].count("智能摇篮产品"), 1)

    def test_context_can_be_reset_after_question_is_sent(self):
        detector = InterviewQuestionDetector()
        detector.add_utterance("这是上一道问题的铺垫。")
        detector.reset_context()
        result = detector.add_utterance("新项目具体负责什么？")
        self.assertNotIn("上一道问题", result["context"])


if __name__ == "__main__":
    unittest.main()
