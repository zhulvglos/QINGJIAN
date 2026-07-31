"""生成免费模型每日快讯。只依赖标准库，供 GitHub Actions 定时执行。"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TZ = timezone(timedelta(hours=8))
UA = "Qingjian-Free-Model-Digest/1.0"
TASKS = {
    "text-generation": "LLM", "image-text-to-text": "VLM",
    "automatic-speech-recognition": "语音识别", "text-to-speech": "语音合成",
    "text-to-image": "生图", "image-to-video": "生视频",
}


def get_json(url, timeout=25):
    request = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


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
        results.append({
            "category": category, "title": title,
            "summary": (str(model.get("description") or "")[:360] or
                        "OpenRouter 当前标记为零价格或 free 路由，额度和可用性可能变化。"),
            "source_name": "OpenRouter", "source_url": f"https://openrouter.ai/{model_id}",
            "permalink": f"openrouter:{model_id}", "free_type": "当前免费 API",
            "access_type": "在线 API", "model_id": model_id, "expires_at": "未公布",
            "verified_at": now.isoformat(timespec="seconds"), "confidence": "高",
            "status": "已核验零价格字段",
        })
    return results[:12]


def huggingface_items(now):
    results = []
    for task, category in TASKS.items():
        query = urlencode({"pipeline_tag": task, "sort": "lastModified", "direction": "-1", "limit": 3})
        for model in get_json("https://huggingface.co/api/models?" + query):
            model_id = str(model.get("modelId") or model.get("id") or "")
            if not model_id:
                continue
            results.append({
                "category": category, "title": model_id,
                "summary": f"近期更新的 {category} 开放权重模型；运行成本、许可证和商用条件请在使用前核对模型卡。",
                "source_name": "Hugging Face", "source_url": f"https://huggingface.co/{model_id}",
                "permalink": f"hf:{model_id}", "free_type": "开放权重（非免费算力）",
                "access_type": "下载/自托管", "model_id": model_id, "expires_at": "长期",
                "verified_at": now.isoformat(timespec="seconds"), "confidence": "高",
                "status": "已核验公开模型页",
            })
    return results


def build_digest():
    now = datetime.now(TZ)
    items, errors = [], []
    for name, collector in (("OpenRouter", openrouter_items), ("Hugging Face", huggingface_items)):
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
        "source": "OpenRouter + Hugging Face", "summary": summary,
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
