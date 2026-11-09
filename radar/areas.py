"""区域权重：高新区、长安区优先（用户公司在高新、很多人住长安）。

高新区不是独立行政区（跨雁塔/长安/鄠邑），所以用「行政区 + 包围盒」两层判断：
  - 逆地理拿 adcode/区名；
  - 名字或地址里带「高新/锦业/科技路/唐延/软件新城/郭杜/韦曲/长安」直接命中；
  - 长安区（610116）整区算优先；
  - 雁塔区（610113）落在高新包围盒内的算高新。
"""
import time

# 高新区大致范围（锦业路/科技路/唐延路/软件新城/鱼化寨/郭杜西一带）
GAOXIN_BBOX = (108.820, 34.140, 108.900, 34.270)   # lng_min, lat_min, lng_max, lat_max
# 长安区（韦曲/郭杜东/航天基地/常宁一带）
CHANGAN_BBOX = (108.900, 34.100, 109.000, 34.200)
CHANGAN_ADCODES = {"610116"}
GAOXIN_KEYWORDS = ("高新", "锦业", "科技路", "唐延", "软件新城", "鱼化", "创业新大陆",
                   "丈八", "郭杜西", "西沣", "发展大道", "西部大道", "智能")
CHANGAN_KEYWORDS = ("长安区", "韦曲", "郭杜", "航天", "常宁", "大兆", "鸣犊", "引镇",
                    "黄良", "子午", "王曲", "杜曲", "兴隆", "太乙宫", "杨庄", "砲里",
                    "外国语大学", "西外", "凤林南路", "文苑路", "府东一路")
HUYI_KEYWORDS = ("秦镇", "秦渡", "鄠邑", "户县")

AREA_BONUS = {"高新区": 15.0, "长安区": 12.0}


def in_bbox(lng: float, lat: float, box) -> bool:
    lng0, lat0, lng1, lat1 = box
    return lng0 <= lng <= lng1 and lat0 <= lat <= lat1


def classify(district: str | None, address: str | None, name: str | None,
             adcode: str | None, lng: float | None, lat: float | None) -> tuple[str | None, float]:
    """返回 (区域标签, 加权分)。"""
    text = f"{district or ''}{address or ''}{name or ''}"
    if any(k in text for k in HUYI_KEYWORDS):
        return "鄠邑区", 0.0
    if any(k in text for k in CHANGAN_KEYWORDS) or adcode in CHANGAN_ADCODES:
        return "长安区", AREA_BONUS["长安区"]
    if any(k in text for k in GAOXIN_KEYWORDS):
        return "高新区", AREA_BONUS["高新区"]
    if lng is not None and lat is not None:
        if in_bbox(lng, lat, GAOXIN_BBOX):
            return "高新区", AREA_BONUS["高新区"]
        if in_bbox(lng, lat, CHANGAN_BBOX):
            return "长安区", AREA_BONUS["长安区"]
    return None, 0.0


def regeo(client, key: str, lng: float, lat: float) -> dict:
    """逆地理：拿 district / adcode（失败返回空）。"""
    params = {"key": key, "location": f"{lng:.6f},{lat:.6f}", "extensions": "base"}
    for attempt in range(3):
        try:
            r = client.get("https://restapi.amap.com/v3/geocode/regeo", params=params, timeout=15)
            data = r.json()
        except Exception:
            time.sleep(1.0)
            continue
        if data.get("status") == "1":
            comp = (data.get("regeocode") or {}).get("addressComponent") or {}
            district = comp.get("district") if isinstance(comp.get("district"), str) else ""
            adcode = comp.get("adcode") if isinstance(comp.get("adcode"), str) else ""
            return {"district": district, "adcode": adcode}
        info = str(data.get("info") or "")
        if "CUQPS" in info or "EXCEEDED" in info:
            time.sleep(1.2 + attempt)
            continue
        break
    return {"district": "", "adcode": ""}
