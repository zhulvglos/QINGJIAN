import re
import time
from collections import deque
from typing import Dict, List, Optional


QUESTION_PATTERNS = (
    r"为什么", r"怎么(?:做|看|理解|解决|处理|考虑)?", r"如何", r"哪些?",
    r"什么", r"多少", r"是否", r"能否", r"有没有", r"是不是", r"可不可以",
    r"你认为", r"你怎么看", r"你会怎么", r"你负责", r"你的贡献",
    r"介绍一下", r"说说", r"谈谈", r"展开(?:一下)?", r"举个例子",
    r"具体(?:是|做|说|讲|负责)", r"结果怎么样", r"遇到过", r"请说明",
)

_QUESTION_RE = re.compile("|".join(QUESTION_PATTERNS), re.I)
_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?", re.S)


def normalize_question(text: str) -> str:
    text = re.sub(r"\s+", "", text or "").strip("，。；;：:、 ")
    if not text:
        return ""
    if text[-1] not in "？?":
        text += "？"
    return text.replace("?", "？")


def question_score(text: str) -> float:
    value = re.sub(r"\s+", "", text or "")
    if not value:
        return 0.0
    score = 0.0
    if value.endswith(("？", "?")):
        score += 0.42
    matches = list(_QUESTION_RE.finditer(value))
    if matches:
        score += min(0.52, 0.3 + 0.11 * len(matches))
    if value.endswith(("吗", "呢", "么")):
        score += 0.22
    if len(value) < 4:
        score -= 0.25
    return max(0.0, min(1.0, score))


def extract_questions(text: str, threshold: float = 0.48) -> List[Dict]:
    found = []
    for raw in _SENTENCE_RE.findall(text or ""):
        sentence = raw.strip()
        score = question_score(sentence)
        if score >= threshold:
            found.append({
                "question": normalize_question(sentence),
                "source": sentence,
                "confidence": round(score, 2),
            })
    return found


class InterviewQuestionDetector:
    """保留短时会议上下文，并过滤重复的候选提问。"""

    def __init__(self, context_size: int = 10, context_seconds: float = 60.0):
        self._context = deque(maxlen=max(2, context_size))
        self.context_seconds = max(10.0, float(context_seconds))
        self._seen = deque(maxlen=20)

    @staticmethod
    def _remove_overlap(previous: str, current: str) -> str:
        """移除音频重叠窗口造成的重复识别前缀。"""
        maximum = min(len(previous), len(current), 120)
        for size in range(maximum, 5, -1):
            if previous[-size:] == current[:size]:
                return current[size:].lstrip("，。；;：:、 ")
        return current

    def reset_context(self) -> None:
        self._context.clear()

    def add_utterance(self, text: str) -> Optional[Dict]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return None
        now = time.monotonic()
        while self._context and now - self._context[0][0] > self.context_seconds:
            self._context.popleft()
        if self._context:
            cleaned = self._remove_overlap(self._context[-1][1], cleaned)
        if not cleaned:
            return None
        self._context.append((now, cleaned))
        candidates = extract_questions(cleaned)
        if not candidates:
            return None
        candidate = candidates[-1]
        question = candidate["question"]
        fingerprint = re.sub(r"\W+", "", question).casefold()
        if not fingerprint or fingerprint in self._seen:
            return None
        self._seen.append(fingerprint)
        context = "\n".join(item[1] for item in self._context)
        candidate["context"] = context
        return candidate
