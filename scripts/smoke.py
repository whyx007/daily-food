"""对运行中的服务做真实链路冒烟测试（会消耗高德额度，仅手工执行）。

用法：python scripts/smoke.py http://127.0.0.1:8123
"""
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8123"
LAT, LNG = 39.90923, 116.397428
TOKEN = "smoke-token"


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=20.0)
    failures: list[str] = []

    health = client.get("/api/health").json()
    print("health:", health["data"]["status"])

    cfg = client.get("/api/config").json()["data"]
    print("config:", cfg["siteName"], cfg["radiusOptions"], "jsKey:", bool(cfg["jsKey"]))

    today = client.get("/api/today", params={"lat": LAT, "lng": LNG, "mode": "area"}).json()
    pick = today["data"]["pick"]
    print("today:", pick["name"], pick["distance"], "m", pick["rating"], "degraded:", today["meta"]["degraded"])
    print("seed:", today["meta"]["seed"])
    if pick["distance"] is None:
        failures.append("today pick 缺少 distance")

    again = client.get("/api/today", params={"lat": LAT, "lng": LNG, "mode": "area", "nonce": 1}).json()
    print("nonce=1:", again["data"]["pick"]["name"])
    if again["data"]["pick"]["id"] == pick["id"]:
        failures.append("换一换没有换店")

    weighted = client.get("/api/today", params={"lat": LAT, "lng": LNG, "mode": "weighted"}).json()
    print("weighted:", weighted["data"]["pick"]["name"], weighted["data"]["pick"]["rating"])

    search = client.get("/api/search", params={"q": "饺子", "lat": LAT, "lng": LNG, "radius": 2000}).json()
    items = search["data"]["items"]
    print("search:", len(items), "first:", items[0]["name"] if items else None)

    added = []
    for item in items[:3]:
        r = client.post("/api/classics", json={"poiid": item["id"]}, headers={"X-Client-Token": TOKEN})
        if r.status_code != 200:
            failures.append(f"名人堂录入失败 {item['name']}: {r.status_code}")
        added.append(item["id"])
    classics = client.get("/api/classics").json()["data"]["items"]
    print("classics:", len(classics))

    classic_today = client.get("/api/today", params={"lat": LAT, "lng": LNG, "mode": "classic"}).json()
    cp = classic_today["data"]["pick"]
    print("classic pick:", cp["name"], cp["distance"], "m", "degraded:", classic_today["meta"]["degraded"])
    if cp["distance"] is None:
        failures.append("classic pick 缺少 distance")

    static = client.get("/api/staticmap", params={"lat": LAT, "lng": LNG})
    print("staticmap:", static.status_code, static.headers.get("content-type"), len(static.content), "bytes")
    if static.status_code != 200 or not static.content:
        failures.append("静态地图失败")

    duplicate = client.get("/api/today", params={"lat": LAT, "lng": LNG, "mode": "area"}).json()
    if duplicate["data"]["pick"]["id"] != pick["id"]:
        failures.append("缓存日结果不稳定（可能是跨日或缓存被覆盖）")

    for poiid in added:
        client.delete(f"/api/classics/{poiid}", headers={"X-Client-Token": TOKEN})

    page = client.get("/")
    print("page:", page.status_code, "map div:", 'id="map"' in page.text, "app.js:", "/app.js" in page.text)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
