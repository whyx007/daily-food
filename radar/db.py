"""SQLite 访问层（独立 radar.db）。"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "radar.db"
SCHEMA = ROOT / "schema.sql"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def upsert_author(conn, a: dict):
    conn.execute(
        """INSERT INTO authors(id,name,platform,tier,followers,note,trust_prior,
                               ad_ratio,trust_final,sample_size,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name, platform=excluded.platform, tier=excluded.tier,
             followers=excluded.followers, note=excluded.note,
             trust_prior=excluded.trust_prior, trust_final=excluded.trust_final,
             updated_at=excluded.updated_at""",
        (a["id"], a["name"], a["platform"], a["tier"], a.get("followers"), a.get("note"),
         a["trust_prior"], a.get("ad_ratio"), a.get("trust_final", a["trust_prior"]),
         a.get("sample_size", 0), now()),
    )


def upsert_claim(conn, c: dict):
    conn.execute(
        """INSERT INTO claims(poi_name,category,sub_category,author_id,url,snippet,
                              published_at,collected_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(poi_name,author_id,url) DO UPDATE SET
             snippet=excluded.snippet, category=excluded.category,
             sub_category=excluded.sub_category, published_at=excluded.published_at""",
        (c["poi_name"], c.get("category"), c.get("sub_category"), c["author_id"],
         c.get("url", ""), c.get("snippet", ""), c.get("published_at"), now()),
    )


def set_claim_verification(conn, claim_id: int, *, poiid, lat, lng, address, note):
    conn.execute(
        """UPDATE claims SET poiid=?, lat=?, lng=?, address=?, verified=?, verify_note=?
           WHERE id=?""",
        (poiid, lat, lng, address, 1 if poiid else 0, note, claim_id),
    )


def set_claim_trust(conn, claim_id: int, trust: float, signals: list):
    conn.execute("UPDATE claims SET trust=?, signals=? WHERE id=?",
                 (trust, json.dumps(signals, ensure_ascii=False), claim_id))


def upsert_poi(conn, p: dict):
    conn.execute(
        """INSERT INTO pois(poiid,name,lat,lng,address,category,rating,cost,mention_count,
                            source_count,consensus,endorsement,area,area_bonus,verified,
                            trust,reason,authors_json,detail_json,first_seen,last_seen,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(poiid) DO UPDATE SET
             name=excluded.name, lat=excluded.lat, lng=excluded.lng,
             address=excluded.address, category=excluded.category,
             rating=excluded.rating, cost=excluded.cost,
             mention_count=excluded.mention_count, source_count=excluded.source_count,
             consensus=excluded.consensus, endorsement=excluded.endorsement,
             area=excluded.area, area_bonus=excluded.area_bonus, verified=excluded.verified,
             trust=excluded.trust, reason=excluded.reason,
             authors_json=excluded.authors_json, detail_json=excluded.detail_json,
             last_seen=excluded.last_seen, updated_at=excluded.updated_at""",
        (p["poiid"], p["name"], p.get("lat"), p.get("lng"), p.get("address"),
         p.get("category"), p.get("rating"), p.get("cost"), p.get("mention_count", 0),
         p.get("source_count", 0), p.get("consensus", 0), p.get("endorsement", 0),
         p.get("area"), p.get("area_bonus", 0), 1 if p.get("verified") else 0,
         p.get("trust", 0), p.get("reason"),
         json.dumps(p.get("authors", []), ensure_ascii=False),
         json.dumps(p.get("detail", {}), ensure_ascii=False),
         p.get("first_seen"), p.get("last_seen"), now()),
    )
