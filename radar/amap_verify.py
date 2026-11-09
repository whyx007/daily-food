"""高德核验：把店名反查成真实 POI（坐标/地址/品类/评分），查不到就是强降权信号。"""
import os
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CITY_ADCODE = "610100"   # 西安


def load_key() -> str:
    key = os.environ.get("AMAP_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("AMAP_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _norm(s: str) -> str:
    return re.sub(r"[（(].*?[)）]|\s|·|・", "", s or "")


def similarity(a: str, b: str) -> float:
    """粗糙但够用的店名相似度：字符级 Jaccard + 包含关系加成。"""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    common = len(set(a) & set(b))
    union = len(set(a) | set(b))
    return round(common / union, 3) if union else 0.0


def search(client: httpx.Client, key: str, name: str) -> list[dict]:
    """按店名做西安范围内的关键字搜索，返回候选 POI（受限流自动重试一次）。"""
    import time

    params = {
        "key": key, "keywords": name, "city": CITY_ADCODE,
        "citylimit": "true", "offset": 10, "page": 1, "extensions": "all",
    }
    data: dict = {}
    for attempt in range(3):
        r = client.get("https://restapi.amap.com/v3/place/text", params=params)
        data = r.json()
        if data.get("status") == "1":
            break
        info = str(data.get("info") or "")
        if "CUQPS" in info or "EXCEEDED" in info:
            time.sleep(1.2 + attempt)
            continue
        return []
    if data.get("status") != "1":
        return []
    out = []
    for raw in data.get("pois") or []:
        loc = raw.get("location") or ""
        if "," not in loc:
            continue
        lng, lat = (float(x) for x in loc.split(",", 1))
        biz = raw.get("biz_ext") or {}
        out.append({
            "poiid": raw.get("id") or "",
            "name": raw.get("name") or "",
            "lat": lat, "lng": lng,
            "address": raw.get("address") or "",
            "category": raw.get("type") or "",
            "rating": _num(biz.get("rating")),
            "cost": _num(biz.get("cost")),
        })
    return out


def _num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def verify(client: httpx.Client, key: str, name: str) -> tuple[dict | None, str]:
    """返回 (最佳匹配 POI, 说明)。匹配度低于阈值按“查无此店”处理。"""
    candidates = search(client, key, name)
    if not candidates:
        return None, "高德查无此店"
    best = max(candidates, key=lambda c: similarity(name, c["name"]))
    sim = similarity(name, best["name"])
    if sim < 0.6:
        return None, f"同名度低（{sim:.0%}，最接近：{best['name']}）"
    return best, f"匹配 {best['name']}（{sim:.0%}）"
