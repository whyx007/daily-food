import math


def quantize_grid(lat: float, lng: float) -> str:
    q_lat = round(lat * 200) / 200
    q_lng = round(lng * 200) / 200
    return f"{q_lat:.3f},{q_lng:.3f}"


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(a))))
