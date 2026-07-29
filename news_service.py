import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from typing import Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DAILY_API = "https://aihot.virxact.com/api/public/daily"
USER_AGENT = "LightNote/0.4 (local Windows desktop app)"
BEIJING_TIMEZONE = timezone(timedelta(hours=8))


class NewsServiceError(RuntimeError):
    pass


def effective_daily_date(now: Optional[datetime] = None) -> str:
    """返回 AI HOT 的业务日期：北京时间每天 08:00 才切换到新一天。"""
    current = now or datetime.now(BEIJING_TIMEZONE)
    if current.tzinfo is not None:
        current = current.astimezone(BEIJING_TIMEZONE).replace(tzinfo=None)
    return (current - timedelta(hours=8)).date().isoformat()


def load_daily_cache(path: Path) -> Optional[Dict]:
    """读取独立新闻缓存；文件缺失或损坏时视为无缓存。"""
    cache_path = Path(path)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not payload.get("date"):
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    return payload


def save_daily_cache(path: Path, payload: Dict) -> None:
    """以原子替换方式保存新闻缓存，避免异常退出留下半个文件。"""
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, temp_name = tempfile.mkstemp(dir=str(cache_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
        os.replace(temp_name, cache_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def normalize_daily(payload: Dict) -> Dict:
    if not isinstance(payload, dict) or not payload.get("date"):
        raise NewsServiceError("日报响应缺少日期")
    items: List[Dict] = []
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        category = str(section.get("label") or "其他")
        for raw in section.get("items") or []:
            if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
                continue
            items.append({
                "category": category,
                "title": str(raw.get("title") or "").strip(),
                "summary": str(raw.get("summary") or "").strip(),
                "source_name": str(raw.get("sourceName") or "AI HOT").strip(),
                "source_url": str(raw.get("sourceUrl") or "").strip(),
                "permalink": str(raw.get("permalink") or "").strip(),
            })
    if not items:
        raise NewsServiceError("日报中没有可展示的新闻")
    attribution = payload.get("attribution") or {}
    return {
        "date": str(payload["date"]),
        "canonical": str(attribution.get("canonical") or "https://aihot.virxact.com/daily"),
        "source": str(attribution.get("source") or "AI HOT"),
        "generated_at": str(payload.get("generatedAt") or ""),
        "items": items,
    }


def fetch_daily(timeout: int = 12) -> Dict:
    request = Request(
        DAILY_API,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise NewsServiceError("请求过于频繁，请稍后再刷新") from exc
        if exc.code in (403, 567):
            raise NewsServiceError("AI HOT 拒绝了本次请求，请检查接入标识") from exc
        raise NewsServiceError(f"AI HOT 服务返回错误：HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise NewsServiceError("无法连接 AI HOT，请检查网络后重试") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NewsServiceError("AI HOT 返回了无法识别的数据") from exc
    return normalize_daily(payload)
