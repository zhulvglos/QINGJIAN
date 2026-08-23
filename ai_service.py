import json
import re
import time
from typing import Callable, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class AIServiceError(RuntimeError):
    pass


STEP_PLAN_MODELS = {
    "step-3.7-flash": (
        "旗舰多模态推理模型，原生支持图片和视频理解，支持 low / medium / high "
        "三档推理强度，适合智能体、代码与复杂分析。"
    ),
    "step-3.5-flash-2603": (
        "针对高频 Agent 场景优化，Token 效率更高、推理速度更快；低推理强度可显著"
        "降低 Token 消耗。"
    ),
    "step-3.5-flash": (
        "196B 总参数、11B 激活参数的稀疏 MoE 模型，高速推理，适合通用分析、"
        "智能体和代码任务。"
    ),
}

REASONING_EFFORTS = {
    "low": "简单问答、摘要、改写和信息提取；速度最快、Token 消耗最低。",
    "medium": "默认推荐，适合一般推理和多步骤任务。",
    "high": "适合复杂推理、数学、规划和代码分析；耗时与Token消耗更高。",
}


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_LLAMA_CPP_PORT = 8080


def ai_provider(base_url: str) -> str:
    normalized = str(base_url or "").strip().lower().rstrip("/")
    if normalized.startswith("https://api.stepfun.com/step_plan"):
        return "step_plan"
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError:
        return "custom"
    if (parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS and
            port == _LLAMA_CPP_PORT and
            parsed.path in ("/v1", "/v1/chat/completions")):
        return "llama_cpp"
    return "custom"


INTERVIEW_TASKS = {
    "summary": (
        "生成面试摘要",
        "请生成结构化面试摘要，包含：面试背景、核心讨论、候选人主要经历、能力关键词、"
        "面试官关注点，以及150至300字总结。只依据原文；缺失信息标记为“未提及”。",
    ),
    "star": (
        "提取问答与STAR案例",
        "请提取面试中的主要问题与回答，并识别项目案例。每个案例按Situation、Task、Action、"
        "Result整理；原文未提供的部分明确标记为“未提及”，不得自行补充经历或数据。",
    ),
    "improve": (
        "分析不足及下一轮准备",
        "请分析回答不清晰、缺少量化结果、可能引起面试官顾虑之处，给出更好的回答组织方式、"
        "下一轮可能追问的问题和具体准备清单。所有判断须说明对应原文依据。",
    ),
}


MEETING_TASKS = {
    "minutes": (
        "生成会议纪要",
        "请按以下固定模板生成结构化会议纪要：一、会议概览（主题、时间、参会角色，"
        "未提及则标记“待确认”）；二、核心结论；三、按议题整理的讨论摘要；四、已确认决策；"
        "五、行动项表格（任务、负责人、截止时间、优先级）；六、风险与阻塞；七、待确认事项；"
        "八、下次会议建议。只依据原文，不得补写原文没有的姓名、日期、结论或任务。",
    ),
    "actions": (
        "提取决策与行动项",
        "请提取会议中明确形成的决策和行动项。行动项使用表格输出：任务、负责人、截止时间、"
        "优先级、原文依据。任何原文没有明确说明的字段标记为“待确认”，不得推测负责人或期限。",
    ),
    "risks": (
        "提取风险与待确认事项",
        "请整理会议中的分歧、风险、阻塞问题、尚未解决的问题和下次会议需确认事项。每项注明"
        "对应原文依据，并区分“已确认事实”和“讨论中的观点”，不得将建议写成已确认决策。",
    ),
}


def chat_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if not url:
        raise AIServiceError("请先填写AI接口地址")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def strip_thinking(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S)
    if "</think>" in cleaned.lower():
        cleaned = re.split(r"</think>", cleaned, maxsplit=1, flags=re.I)[-1]
    if re.match(r"^\s*<think>", cleaned, flags=re.I):
        return ""
    return cleaned.strip()


def chunk_interview_text(text: str, max_chars: int = 12000) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    paragraphs = re.split(r"(?=\n?说话人\s*\d+\s*[:：])", text)
    if len(paragraphs) == 1:
        paragraphs = text.splitlines(keepends=True)
    chunks, current = [], ""
    for part in paragraphs:
        if len(part) > max_chars:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(part[i:i + max_chars] for i in range(0, len(part), max_chars))
        elif current and len(current) + len(part) > max_chars:
            chunks.append(current.strip())
            current = part
        else:
            current += part
    if current.strip():
        chunks.append(current.strip())
    return chunks


def parse_sse_lines(lines: Iterable[bytes], cancelled=None,
                    on_delta: Optional[Callable[[str], None]] = None,
                    metadata: Optional[Dict] = None,
                    deadline: Optional[float] = None) -> str:
    parts = []
    emitted_length = 0
    for raw in lines:
        if deadline is not None and time.monotonic() >= deadline:
            raise AIServiceError("AI请求超过整体时限")
        if cancelled and cancelled.is_set():
            raise AIServiceError("已取消生成")
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
            choice = payload.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            if metadata is not None:
                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    metadata["finish_reason"] = finish_reason
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning:
                    metadata["reasoning_chars"] = (
                        metadata.get("reasoning_chars", 0) + len(str(reasoning)))
            content = delta.get("content")
            if content:
                parts.append(content)
                if on_delta:
                    visible = strip_thinking("".join(parts))
                    if len(visible) > emitted_length:
                        on_delta(visible[emitted_length:])
                        emitted_length = len(visible)
        except (ValueError, IndexError, AttributeError):
            continue
    return "".join(parts)


def stream_chat_completion(config: Dict, messages: List[Dict], cancelled=None,
                           max_tokens: Optional[int] = 4096,
                           on_delta: Optional[Callable[[str], None]] = None,
                           retry_empty: bool = False,
                           response_format: Optional[Dict] = None,
                           temperature: float = 0.6,
                           disable_thinking: bool = False,
                           total_timeout: Optional[int] = None) -> str:
    token = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or "").strip()
    provider = ai_provider(str(config.get("base_url") or ""))
    if not token:
        raise AIServiceError("请先在设置中保存API Key")
    if not model:
        raise AIServiceError("请先填写AI模型名称")
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": float(temperature),
        "top_p": 0.95,
    }
    if response_format:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    reasoning_effort = str(config.get("reasoning_effort") or "").strip().lower()
    if provider == "llama_cpp" and disable_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    elif provider != "llama_cpp" and reasoning_effort in {"low", "medium", "high"}:
        payload["reasoning_effort"] = reasoning_effort
    last_metadata = {}
    attempts = 2 if retry_empty else 1
    deadline = (time.monotonic() + max(1, int(total_timeout))
                if total_timeout is not None else None)
    for attempt in range(attempts):
        if deadline is not None and time.monotonic() >= deadline:
            raise AIServiceError("AI请求超过整体时限")
        request_payload = dict(payload)
        if attempt:
            request_payload["messages"] = list(messages) + [{
                "role": "user",
                "content": "请停止展开分析，立即直接输出最终答案正文。",
            }]
        body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            chat_url(str(config.get("base_url") or "")), data=body, method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        try:
            socket_timeout = int(config.get("timeout", 180))
            if deadline is not None:
                socket_timeout = min(socket_timeout, max(1, int(deadline - time.monotonic())))
            with urlopen(request, timeout=socket_timeout) as response:
                last_metadata = {}
                result = parse_sse_lines(
                    response, cancelled, on_delta, last_metadata, deadline=deadline)
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except OSError:
                pass
            if exc.code in (401, 403):
                raise AIServiceError("AI接口鉴权失败，请检查Token") from exc
            raise AIServiceError(f"AI接口返回HTTP {exc.code}：{detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise AIServiceError("无法连接AI服务或请求超时") from exc
        final = strip_thinking(result)
        if final:
            return final
    finish = last_metadata.get("finish_reason") or "未知"
    reasoning = last_metadata.get("reasoning_chars", 0)
    raise AIServiceError(
        f"AI服务未返回最终答案（结束原因：{finish}，推理字符：{reasoning}），已自动重试一次")


def analyze_interview(task: str, text: str, config: Dict,
                      status: Optional[Callable[[str], None]] = None,
                      cancelled=None) -> str:
    if task not in INTERVIEW_TASKS:
        raise AIServiceError("未知的面试分析任务")
    title, instruction = INTERVIEW_TASKS[task]
    chunks = chunk_interview_text(text)
    if not chunks:
        raise AIServiceError("当前笔记没有可分析的正文")
    system = ("你是严谨的中文面试复盘助手。只允许依据用户提供的面试转写稿分析，"
              "不得编造事实、经历、数据或面试官意图。只输出最终结果，不输出思考过程。")
    if len(chunks) == 1:
        if status:
            status(f"正在{title}……")
        return stream_chat_completion(config, [
            {"role": "system", "content": system},
            {"role": "user", "content": f"任务：{instruction}\n\n面试转写稿：\n{chunks[0]}"},
        ], cancelled)

    partials = []
    for index, chunk in enumerate(chunks, 1):
        if cancelled and cancelled.is_set():
            raise AIServiceError("已取消生成")
        if status:
            status(f"正在分析第 {index}/{len(chunks)} 段……")
        partials.append(stream_chat_completion(config, [
            {"role": "system", "content": system},
            {"role": "user", "content":
             f"这是完整面试的第{index}/{len(chunks)}段。请提取与最终任务相关的事实和原文依据。\n"
             f"最终任务：{instruction}\n\n本段转写：\n{chunk}"},
        ], cancelled, max_tokens=1800))
    if status:
        status("正在合并分段结果……")
    merged = "\n\n".join(f"【第{i}段】\n{part}" for i, part in enumerate(partials, 1))
    return stream_chat_completion(config, [
        {"role": "system", "content": system},
        {"role": "user", "content": f"请根据以下分段提取结果完成任务：{instruction}\n\n{merged}"},
    ], cancelled)


def analyze_meeting(task: str, text: str, config: Dict,
                    status: Optional[Callable[[str], None]] = None,
                    cancelled=None) -> str:
    if task not in MEETING_TASKS:
        raise AIServiceError("未知的会议总结任务")
    title, instruction = MEETING_TASKS[task]
    chunks = chunk_interview_text(text)
    if not chunks:
        raise AIServiceError("当前笔记没有可分析的会议正文")
    system = (
        "你是严谨的中文会议纪要助手。只允许依据用户提供的会议转写稿整理，不得编造"
        "参会者、时间、负责人、期限、决策或数据。原文不明确的信息统一标记为“待确认”。"
        "区分讨论观点、建议和已确认决策。只输出最终结果，不输出思考过程。"
    )
    if len(chunks) == 1:
        if status:
            status(f"正在{title}……")
        return stream_chat_completion(config, [
            {"role": "system", "content": system},
            {"role": "user", "content": f"任务：{instruction}\n\n会议转写稿：\n{chunks[0]}"},
        ], cancelled)

    partials = []
    for index, chunk in enumerate(chunks, 1):
        if cancelled and cancelled.is_set():
            raise AIServiceError("已取消生成")
        if status:
            status(f"正在分析第 {index}/{len(chunks)} 段会议内容……")
        partials.append(stream_chat_completion(config, [
            {"role": "system", "content": system},
            {"role": "user", "content":
             f"这是完整会议的第{index}/{len(chunks)}段。请仅提取与最终任务有关的事实和原文依据。\n"
             f"最终任务：{instruction}\n\n本段转写：\n{chunk}"},
        ], cancelled, max_tokens=1800))
    if status:
        status("正在合并会议分段结果……")
    merged = "\n\n".join(f"【第{i}段】\n{part}" for i, part in enumerate(partials, 1))
    return stream_chat_completion(config, [
        {"role": "system", "content": system},
        {"role": "user", "content": f"请根据以下分段提取结果完成任务：{instruction}\n\n{merged}"},
    ], cancelled)


def answer_interview_question(question: str, context: str, knowledge: str,
                              config: Dict, cancelled=None,
                              knowledge_sources: Optional[List[str]] = None,
                              on_delta: Optional[Callable[[str], None]] = None) -> str:
    question = (question or "").strip()
    if not question:
        raise AIServiceError("没有可回答的面试问题")
    knowledge = (knowledge or "").strip()[-12000:]
    source_text = "、".join(knowledge_sources or []) or "无命中资料"
    prompt = (
        "请先结合最近对话上下文还原完整问题，然后直接回答。只输出一段自然、简洁、可以直接"
        "口述的中文答案，控制在100至250个汉字；先直接回答结论，再用两三个关键句说明。"
        "不要输出标题、Markdown、回答建议、STAR模板、分析过程或补充要点。"
        "优先使用面试知识库资料。涉及候选人个人经历、项目、职责、数据或成果时，只能使用知识库"
        "中明确存在的事实，不得虚构；知识库没有相关内容时，应给出不虚构具体经历和数字的自然"
        "回答框架。一般知识和技术问题（包括历史常识）在知识库没有答案时，可以使用可靠的"
        "通用知识直接回答。遇到英文缩写、协议名、框架名或产品名时，必须先依据知识库中的"
        "直接定义；知识库没有直接依据且不能可靠确认时，应明确说明术语需要确认，绝不能猜测"
        "缩写全称、用途或虚构定义。\n\n"
        f"识别到的问题：{question}\n\n最近对话上下文：\n{context or '无'}\n\n"
        f"命中的知识库来源：{source_text}\n\n"
        f"面试知识库相关片段：\n{knowledge or '未检索到直接相关资料，请按通用知识或回答框架处理。'}"
    )
    return stream_chat_completion(config, [
        {"role": "system", "content": (
            "你是中文面试即时回答助手。只输出可直接口述的答案正文，不使用任何模板或格式标题。")},
        {"role": "user", "content": prompt},
    ], cancelled, max_tokens=None, on_delta=on_delta, retry_empty=True,
        disable_thinking=True)


def choose_interview_answer_provider(mode: str, terminology_risk: Dict,
                                     knowledge_sources: List[str]):
    """为实时面试回答选择本地或云端模型，并返回可展示的原因。"""
    if mode == "cloud_quality":
        return "step_plan", "已选择高质量云端模式"
    if mode == "local_fast":
        return "llama_cpp", "已选择极速本地模式"
    risk = dict(terminology_risk or {})
    if risk.get("correction_applied"):
        return "step_plan", "语音中存在专业术语纠正"
    unknown = list(risk.get("unknown_acronyms") or [])
    if unknown:
        return "step_plan", "存在未确认缩写：" + "、".join(unknown[:3])
    if not knowledge_sources:
        return "step_plan", "知识库没有直接命中"
    return "llama_cpp", "知识库有依据，使用本地模型快速回答"
