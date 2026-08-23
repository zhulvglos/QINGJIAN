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

    def test_detects_sensevoice_question_with_period(self):
        questions = extract_questions("呃，什么是agent，你解释一下。")
        self.assertEqual(len(questions), 1)
        self.assertIn("什么是agent", questions[0]["question"])

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

    def test_forced_audio_chunks_wait_for_final_pause(self):
        detector = InterviewQuestionDetector()
        self.assertIsNone(detector.add_utterance(
            "我看到你负责过一个复杂的商业空间项目，", finalize=False))
        self.assertIsNone(detector.add_utterance(
            "当时既要协调设计施工，也要控制成本，", finalize=False))
        result = detector.add_utterance("你最后是怎么解决这些冲突的？")
        self.assertIn("商业空间项目", result["question"])
        self.assertIn("怎么解决这些冲突", result["question"])

    def test_reset_discards_unfinished_long_question(self):
        detector = InterviewQuestionDetector()
        detector.add_utterance("这是尚未结束的问题前半段", finalize=False)
        detector.reset_context()
        result = detector.add_utterance("新项目具体负责什么？")
        self.assertNotIn("尚未结束", result["question"])

    def test_empty_final_chunk_flushes_recognized_continuation(self):
        detector = InterviewQuestionDetector()
        detector.add_utterance("你会怎么协调设计和施工？", finalize=False)
        result = detector.add_utterance("", finalize=True)
        self.assertIn("怎么协调设计和施工", result["question"])


if __name__ == "__main__":
    unittest.main()
