"""把 claims 聚合成 pois，按两个维度打分：

  1) consensus（重合度/稳定性）：有多少个独立信号源、其层级权重、提及时间跨度
  2) endorsement（博主力荐）：博主线索的可信度、博主数量、"力荐"类措辞

  最终可信度 = 0.6 * consensus + 0.4 * endorsement
"""
import json
import re
from datetime import datetime

from radar import adfilter, db
from radar.amap_verify import verify

TIER_WEIGHT = {"private": 1.00, "doc": 0.90, "laozihao": 0.85, "zhihu": 0.70,
               "media": 0.60, "blogger": 0.50}

# 博主力荐的措辞信号
ENDORSE_WORDS = r"力荐|强烈推荐|必吃|最爱|常去|吃了\s*\d+\s*年|我推荐|闭眼冲|直接安利|按头安利"


def _parse_date(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s[:len(fmt.replace('%Y', 'YYYY').replace('%m', 'MM').replace('%d', 'DD'))], fmt)
        except ValueError:
            continue
    return None


def _span_days(rows) -> int:
    dates = [d for d in (_parse_date(r["published_at"]) for r in rows) if d]
    if len(dates) < 2:
        return 0
    return (max(dates) - min(dates)).days


def score_authors(conn) -> int:
    rows = conn.execute("SELECT id, trust_prior, ad_ratio, sample_size FROM authors").fetchall()
    for row in rows:
        trust = row["trust_prior"]
        if row["ad_ratio"] is not None:
            w = min(1.0, (row["sample_size"] or 0) / 20)
            trust = trust * (1 - w) + (1 - row["ad_ratio"]) * w
        conn.execute("UPDATE authors SET trust_final=?, updated_at=? WHERE id=?",
                     (round(max(0.05, min(1.0, trust)), 3), db.now(), row["id"]))
    conn.commit()
    return len(rows)


def score_claims(conn) -> int:
    rows = conn.execute("""SELECT c.id, c.snippet, a.trust_final
                           FROM claims c JOIN authors a ON a.id=c.author_id""").fetchall()
    for row in rows:
        trust, signals = adfilter.claim_trust(row["trust_final"], row["snippet"] or "")
        db.set_claim_trust(conn, row["id"], trust, signals)
    conn.commit()
    return len(rows)


def verify_claims(conn, client, key: str, limit: int | None = None) -> tuple[int, int]:
    import time

    sql = "SELECT id, poi_name FROM claims WHERE verified=0"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    ok = bad = 0
    for row in rows:
        poi, note = verify(client, key, row["poi_name"])
        time.sleep(0.35)  # 高德个人 Key 并发受限，逐条限速
        if poi:
            db.set_claim_verification(conn, row["id"], poiid=poi["poiid"], lat=poi["lat"],
                                      lng=poi["lng"], address=poi["address"], note=note)
            ok += 1
        else:
            db.set_claim_verification(conn, row["id"], poiid=None, lat=None, lng=None,
                                      address=None, note=note)
            bad += 1
    conn.commit()
    return ok, bad


def _consensus(items) -> tuple[float, dict]:
    """重合度/稳定性：独立来源权重之和 + 时间跨度加成。"""
    tiers = {}
    for r in items:
        tiers.setdefault(r["tier"], set()).add(r["author"])
    # 每个来源按层级权重计，同层级多个来源各算一份
    weight_sum = sum(TIER_WEIGHT.get(r["tier"], 0.5) for r in items if r["author"])
    distinct = len({(r["author"]) for r in items})
    base = min(1.0, weight_sum / 1.6) * 80          # 两个独立强源即可接近满分
    span = _span_days(items)
    bonus = 8 if span >= 180 else (15 if span >= 365 else 0)
    score = round(min(100.0, base + bonus), 1)
    detail = {"distinct_sources": distinct, "weight_sum": round(weight_sum, 2),
              "span_days": span, "tier_count": len(tiers)}
    return score, detail


def _endorsement(items) -> tuple[float, dict]:
    """博主力荐：只看 blogger 层级线索。"""
    blogger_items = [r for r in items if r["tier"] == "blogger"]
    if not blogger_items:
        return 0.0, {"blogger_count": 0, "strong_words": 0}
    best = max((r["trust"] or 0) for r in blogger_items)
    strong = sum(1 for r in blogger_items if re.search(ENDORSE_WORDS, r["snippet"] or ""))
    score = best * 100
    if len(blogger_items) >= 2:
        score += min(20, (len(blogger_items) - 1) * 10)
    score += min(15, strong * 8)
    return round(min(100.0, score), 1), {"blogger_count": len(blogger_items), "strong_words": strong}


def consolidate(conn) -> int:
    rows = conn.execute("""
        SELECT c.poiid, c.poi_name, c.trust, c.snippet, c.address, c.lat, c.lng,
               c.published_at, c.collected_at, c.category, a.name AS author, a.tier
        FROM claims c JOIN authors a ON a.id=c.author_id
    """).fetchall()

    groups = {}
    for row in rows:
        key = row["poiid"] or ("unverified:" + row["poi_name"])
        groups.setdefault(key, []).append(row)

    conn.execute("DELETE FROM pois")
    for key, items in groups.items():
        if key.startswith("unverified:"):
            continue
        best = max(items, key=lambda r: r["trust"] or 0)
        authors = sorted({r["author"] for r in items})
        consensus, c_info = _consensus(items)
        endorsement, e_info = _endorsement(items)
        trust = round(0.6 * consensus + 0.4 * endorsement + 10, 1)  # +10 已通过高德核验
        trust = max(0.0, min(100.0, trust))

        dates = [r["published_at"] or r["collected_at"] for r in items]
        db.upsert_poi(conn, {
            "poiid": key, "name": best["poi_name"],
            "lat": best["lat"], "lng": best["lng"], "address": best["address"],
            "category": best["category"],
            "mention_count": len(items), "source_count": len(authors),
            "consensus": consensus, "endorsement": endorsement,
            "trust": trust, "reason": best["snippet"], "authors": authors,
            "detail": {"consensus": c_info, "endorsement": e_info, "verified": True},
            "first_seen": min(dates) if dates else None,
            "last_seen": max(dates) if dates else None,
        })
    conn.commit()
    return len(groups)
