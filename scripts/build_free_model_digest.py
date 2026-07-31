"""生成免费模型每日快讯。只依赖标准库，供 GitHub Actions 定时执行。"""
import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen


TZ = timezone(timedelta(hours=8))
UA = "Qingjian-Free-Model-Digest/1.0"
def get_json(url, timeout=25):
    request = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def describe_model(model, category):
    model_id = str(model.get("id") or "").lower()
    description = str(model.get("description") or "").strip()
    text = description.lower()
    context = int(model.get("context_length") or 0)
    signals = model_id + " " + text
    feature_parts = []
    use_cases = []

    is_code = any(word in signals for word in
                  ("code", "coding", "coder", "software engineering", "agentic"))
    is_reasoning = any(word in signals for word in
                       ("reason", "reasoning", "r1", "qwq", "math", "logic"))
    if is_code and "agentic" in signals:
        feature_parts.append("面向编程智能体与软件开发任务优化")
        use_cases.extend(("仓库级代码理解", "编程智能体", "代码生成与修改"))
    elif is_code:
        feature_parts.append("重点强化代码理解、生成与修改能力")
        use_cases.extend(("代码生成", "代码审查", "故障排查"))
    if is_reasoning:
        feature_parts.append("强调复杂推理与分步分析能力")
        use_cases.extend(("数学与逻辑推理", "复杂方案分析"))
    if category == "VLM":
        feature_parts.append("支持图片与文本联合理解")
        use_cases.extend(("图片问答", "图表和截图分析", "视觉内容提取"))
    elif not is_code and not is_reasoning:
        feature_parts.append("提供通用文本理解、指令执行与内容生成能力")
        use_cases.extend(("知识问答", "摘要改写", "资料整理"))

    if "mixture-of-experts" in text or "mixture of experts" in text:
        feature_parts.append("采用混合专家架构，在模型容量与推理效率之间取得平衡")
    if "sparse" in text and ("expert" in text or "moe" in text):
        feature_parts.append("使用稀疏专家激活机制以降低单次推理开销")
    parameter_match = re.search(
        r"([\d.]+)\s*b(?:illion)?\s+(?:total\s+)?parameters?.{0,80}?"
        r"([\d.]+)\s*b(?:illion)?\s+(?:parameters?\s+)?active", text)
    if parameter_match:
        feature_parts.append(
            f"总参数约 {parameter_match.group(1)}B，单次激活约 {parameter_match.group(2)}B")
    elif "30b total parameters" in text and "3b active" in text:
        feature_parts.append("总参数约 30B，单次激活约 3B")
    if "first" in text and ("family" in text or "series" in text):
        feature_parts.append("来源介绍将其定位为该模型系列的首款产品")
    if any(word in text for word in ("safety", "guardrail", "content moderation")):
        feature_parts.append("面向内容安全检测与风险分类设计")
        use_cases.extend(("内容审核", "安全护栏", "风险分类"))
    if context:
        feature_parts.append(f"支持约 {context:,} tokens 的上下文窗口")
        if context >= 100000:
            use_cases.extend(("长文档分析", "大型代码库上下文处理" if is_code else "多资料综合分析"))

    feature_parts = list(dict.fromkeys(feature_parts))
    use_cases = list(dict.fromkeys(use_cases))
    model_name = str(model.get("name") or model.get("id") or "该模型")
    features = f"{model_name} 是一款" + "；".join(feature_parts) + "。"
    scenarios = "适合用于" + "、".join(use_cases) + "。"
    return features, scenarios, description[:500]


def openrouter_items(now):
    payload = get_json("https://openrouter.ai/api/v1/models")
    results = []
    for model in payload.get("data") or []:
        pricing = model.get("pricing") or {}
        model_id = str(model.get("id") or "")
        zero = model_id.endswith(":free") or (
            "prompt" in pricing and "completion" in pricing and
            all(str(pricing.get(key)) in ("0", "0.0") for key in ("prompt", "completion")))
        if not model_id or not zero:
            continue
        architecture = model.get("architecture") or {}
        inputs = architecture.get("input_modalities") or []
        category = "VLM" if "image" in inputs else "LLM"
        title = str(model.get("name") or model_id)
        description = str(model.get("description") or "").strip()
        if len(description) < 40:
            continue
        features, use_cases, description = describe_model(model, category)
        results.append({
            "category": category, "title": title,
            "summary": (description or
                        "OpenRouter 当前标记为免费路由，额度和可用性可能变化。"),
            "features": features, "use_cases": use_cases,
            "source_name": "OpenRouter", "source_url": f"https://openrouter.ai/{model_id}",
            "permalink": f"openrouter:{model_id}", "free_type": "当前免费 API",
            "access_type": "在线 API", "model_id": model_id,
            "expires_at": "官方未公布截止日期，可能随时调整",
            "verified_at": now.isoformat(timespec="seconds"), "confidence": "高",
            "status": "已核验零价格字段",
        })
    return results[:20]


def build_digest():
    now = datetime.now(TZ)
    items, errors = [], []
    for name, collector in (("OpenRouter", openrouter_items),):
        try:
            items.extend(collector(now))
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    unique = {}
    for item in items:
        unique[item["permalink"]] = item
    items = list(unique.values())
    if not items:
        raise RuntimeError("所有来源均无可用结果：" + "; ".join(errors))
    counts = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    summary = "；".join(f"{key} {value}项" for key, value in counts.items())
    return {
        "date": now.date().isoformat(), "generated_at": now.isoformat(timespec="seconds"),
        "canonical": "https://github.com/zhulvglos/QINGJIAN/releases/tag/free-model-daily",
        "source": "OpenRouter 在线免费 API", "summary": summary,
        "errors": errors, "items": items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_digest(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
