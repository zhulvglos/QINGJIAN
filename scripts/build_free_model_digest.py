"""生成免费模型每日快讯。只依赖标准库，供 GitHub Actions 定时执行。"""
import argparse
import html
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen


TZ = timezone(timedelta(hours=8))
UA = "Qingjian-Free-Model-Digest/1.0"
def get_json(url, timeout=25, headers=None):
    request_headers = {"User-Agent": UA, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
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


def siliconflow_items(now):
    """读取硅基流动的 OpenAI 兼容模型目录，只保留明确为零价的 API。

    该接口需要用户在 GitHub Actions 中配置 SILICONFLOW_API_KEY；未配置时跳过，
    避免把无法核验的模型误报为免费。
    """
    api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    if not api_key:
        return []
    url = os.getenv("SILICONFLOW_MODELS_URL", "https://api.siliconflow.cn/v1/models")
    payload = get_json(url, headers={"Authorization": f"Bearer {api_key}"})
    results = []
    for model in payload.get("data") or []:
        model_id = str(model.get("id") or "")
        pricing = model.get("pricing") or model.get("price") or {}
        prompt = pricing.get("prompt", pricing.get("input", pricing.get("input_price")))
        completion = pricing.get("completion", pricing.get("output", pricing.get("output_price")))
        zero = prompt is not None and completion is not None and all(
            str(value) in ("0", "0.0", "0.00") for value in (prompt, completion))
        if not model_id or not zero:
            continue
        architecture = model.get("architecture") or {}
        inputs = architecture.get("input_modalities") or []
        category = "VLM" if "image" in inputs else "LLM"
        description = str(model.get("description") or model.get("name") or model_id).strip()
        if len(description) < 20:
            description = f"硅基流动目录中的 {model_id}，当前返回零价格 API 字段。"
        features, use_cases, short_description = describe_model(model, category)
        results.append({
            "category": category, "title": str(model.get("name") or model_id),
            "summary": short_description or description[:500],
            "features": features, "use_cases": use_cases,
            "source_name": "硅基流动", "source_url": "https://www.siliconflow.cn/models",
            "permalink": f"siliconflow:{model_id}", "free_type": "当前免费 API（以平台额度为准）",
            "access_type": "在线 API", "model_id": model_id,
            "expires_at": "官方未公布截止日期，可能随时调整",
            "verified_at": now.isoformat(timespec="seconds"), "confidence": "中",
            "status": "已核验目录零价格字段",
        })
    return results[:20]


def siliconflow_public_items(now):
    """从硅基流动公开模型页读取免费或部分免费的 API 模型。

    模型目录 API 不一定返回活动额度或价格字段，因此这里补充公开页面核验。
    输入或输出任一侧为 0 即纳入，但在免费方式中明确标注另一侧是否收费，
    避免把“部分免费”误报成永久免费。
    """
    url = os.getenv("SILICONFLOW_PUBLIC_MODELS_URL", "https://www.siliconflow.cn/models")
    request = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urlopen(request, timeout=25) as response:
        page = html.unescape(response.read().decode("utf-8", errors="replace"))
    results = []
    marker = '<div class="mb-[14px] group-hover:hidden">'
    for card in page.split(marker)[1:]:
        name_match = re.search(
            r'<div class="text-slate-800 text-\[16px\] font-semibold truncate mb-\[4px\]">\s*([^<]+)', card)
        if not name_match:
            continue
        model_id = re.sub(r"\s+", " ", name_match.group(1)).strip()
        price_match = re.search(
            r"输入:\s*<span[^>]*>￥\s*(?:<!--.*?-->)?\s*([\d.]+).*?输出:\s*<span[^>]*>￥\s*(?:<!--.*?-->)?\s*([\d.]+)",
            card, re.S)
        if not price_match or all(float(value) != 0 for value in price_match.groups()):
            continue
        input_price, output_price = (float(value) for value in price_match.groups())
        desc_match = re.search(
            r'<div class="text-slate-800 text-\[14px\] line-clamp-2 mb-\[8px\]">\s*(.*?)</div>',
            card, re.S)
        description = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip() if desc_match else ""
        category_match = re.search(r'ant-tag-blue[^>]*>\s*([^<]+)', card)
        category_text = category_match.group(1).strip() if category_match else "对话"
        category = "VLM" if any(word in category_text for word in ("视觉", "图像")) else "LLM"
        model = {"id": model_id, "name": model_id, "description": description}
        features, use_cases, summary = describe_model(model, category)
        results.append({
            "category": category, "title": model_id,
            "summary": summary or description[:500] or "硅基流动公开页面标记为零价格 API。",
            "features": features, "use_cases": use_cases,
            "source_name": "硅基流动", "source_url": url,
            "permalink": f"siliconflow-public:{model_id}",
            "free_type": ("当前免费 API（输入/输出均为 0）" if input_price == output_price == 0
                          else f"部分免费 API（输入 ￥{input_price:g}/M，输出 ￥{output_price:g}/M）"),
            "access_type": "在线 API", "model_id": model_id,
            "expires_at": "官方未公布截止日期，可能随时调整",
            "verified_at": now.isoformat(timespec="seconds"), "confidence": "高",
            "status": "已核验公开模型页价格；免费侧可能随时调整",
        })
    return results[:20]


def build_digest():
    now = datetime.now(TZ)
    items, errors = [], []
    collectors = [("OpenRouter", openrouter_items)]
    if os.getenv("SILICONFLOW_API_KEY", "").strip():
        collectors.append(("硅基流动", siliconflow_items))
    collectors.append(("硅基流动公开模型页", siliconflow_public_items))
    for name, collector in collectors:
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
        "source": "OpenRouter 与已配置的国内在线 API 来源", "summary": summary,
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
