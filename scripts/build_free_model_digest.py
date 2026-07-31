"""生成免费模型每日快讯。只依赖标准库，供 GitHub Actions 定时执行。"""
import argparse
import json
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
    context = int(model.get("context_length") or 0)
    features = []
    use_cases = []
    if any(word in model_id for word in ("reason", "r1", "qwq")):
        features.append("强化复杂推理与分步分析")
        use_cases.extend(("数学与逻辑推理", "复杂方案分析"))
    if any(word in model_id for word in ("code", "coder", "devstral")):
        features.append("面向代码理解与生成优化")
        use_cases.extend(("代码生成", "代码审查与排错"))
    if category == "VLM":
        features.append("支持图片与文本联合理解")
        use_cases.extend(("图片问答", "图表和截图分析", "视觉内容提取"))
    else:
        features.append("支持通用文本理解与生成")
        use_cases.extend(("问答助手", "摘要改写", "知识整理"))
    if context:
        features.append(f"上下文窗口约 {context:,} tokens")
        if context >= 100000:
            use_cases.append("长文档分析")
    features = list(dict.fromkeys(features))
    use_cases = list(dict.fromkeys(use_cases))
    return "；".join(features), "、".join(use_cases), description[:360]


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
