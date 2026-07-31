import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from news_service import NewsServiceError


FREE_MODEL_DAILY_URL = (
    "https://github.com/zhulvglos/QINGJIAN/releases/download/"
    "free-model-daily/daily.json"
)
BEIJING_TIMEZONE = timezone(timedelta(hours=8))
USER_AGENT = "LightNote/0.5 (free model digest)"


def effective_flash_date(now: Optional[datetime] = None) -> str:
    """快讯在北京时间 09:00 切换，给云端采集留出生成时间。"""
    current = now or datetime.now(BEIJING_TIMEZONE)
    if current.tzinfo is not None:
        current = current.astimezone(BEIJING_TIMEZONE).replace(tzinfo=None)
    return (current - timedelta(hours=9)).date().isoformat()


def normalize_free_model_digest(payload: Dict) -> Dict:
    if not isinstance(payload, dict) or not payload.get("date"):
        raise NewsServiceError("免费模型快讯缺少日期")
    items = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        item = {key: str(raw.get(key) or "").strip() for key in (
            "category", "title", "summary", "source_name", "source_url",
            "permalink", "free_type", "access_type", "model_id", "expires_at",
            "verified_at", "confidence", "status")}
        item["category"] = item["category"] or "其他模型"
        item["source_name"] = item["source_name"] or "公开来源"
        item["permalink"] = item["permalink"] or item["source_url"]
        items.append(item)
    if not items:
        raise NewsServiceError("今日免费模型快讯暂无可展示内容")
    return {
        "date": str(payload["date"]),
        "canonical": str(payload.get("canonical") or FREE_MODEL_DAILY_URL),
        "source": str(payload.get("source") or "轻笺免费模型快讯"),
        "generated_at": str(payload.get("generated_at") or ""),
        "summary": str(payload.get("summary") or ""),
        "items": items,
    }


def fetch_free_model_digest(timeout: int = 12) -> Dict:
    request = Request(FREE_MODEL_DAILY_URL, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise NewsServiceError("免费模型快讯尚未生成") from exc
        raise NewsServiceError(f"快讯服务返回错误：HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise NewsServiceError("无法连接免费模型快讯，请检查网络") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NewsServiceError("免费模型快讯数据格式异常") from exc
    return normalize_free_model_digest(payload)
