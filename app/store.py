import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS area_pool (
  date TEXT NOT NULL, grid TEXT NOT NULL, radius INTEGER NOT NULL,
  category TEXT NOT NULL DEFAULT 'all',
  payload TEXT NOT NULL, fetched_at INTEGER NOT NULL,
  PRIMARY KEY (date, grid, radius, category)
);
CREATE TABLE IF NOT EXISTS search_cache (
  query_key TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS classics (
  poiid TEXT PRIMARY KEY, name TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
  rating TEXT, cost TEXT, type TEXT, address TEXT, note TEXT,
  added_by TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS call_log (
  date TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_pool(self, date: str, grid: str, radius: int, category: str = "all"):
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, fetched_at FROM area_pool WHERE date=? AND grid=? AND radius=? AND category=?",
                (date, grid, radius, category),
            ).fetchone()
        return None if row is None else (json.loads(row["payload"]), row["fetched_at"])

    def put_pool(self, date, grid, radius, category, payload, fetched_at) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO area_pool (date, grid, radius, category, payload, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (date, grid, radius, category, json.dumps(payload, ensure_ascii=False), fetched_at),
            )
            self._conn.commit()

    def get_latest_pool(self, grid: str, radius: int, category: str = "all"):
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, fetched_at, date FROM area_pool "
                "WHERE grid=? AND radius=? AND category=? ORDER BY date DESC LIMIT 1",
                (grid, radius, category),
            ).fetchone()
        return None if row is None else (json.loads(row["payload"]), row["fetched_at"], row["date"])

    def get_search(self, query_key: str, ttl: int = 300, now: int | None = None):
        now = int(time.time()) if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, fetched_at FROM search_cache WHERE query_key=?", (query_key,)
            ).fetchone()
        if row is None or now - row["fetched_at"] > ttl:
            return None
        return json.loads(row["payload"]), row["fetched_at"]

    def put_search(self, query_key: str, payload, fetched_at: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO search_cache (query_key, payload, fetched_at) VALUES (?, ?, ?)",
                (query_key, json.dumps(payload, ensure_ascii=False), fetched_at),
            )
            self._conn.commit()

    def upsert_classic(self, poi: dict, added_by: str, note: str | None) -> None:
        with self._lock:
            existing = self._conn.execute(
                "SELECT added_by, created_at FROM classics WHERE poiid=?", (poi["id"],)
            ).fetchone()
            created_at = existing["created_at"] if existing else int(time.time())
            owner = existing["added_by"] if existing else added_by
            self._conn.execute(
                "INSERT OR REPLACE INTO classics "
                "(poiid, name, lat, lng, rating, cost, type, address, note, added_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (poi["id"], poi["name"], poi["lat"], poi["lng"], poi.get("rating"), poi.get("cost"),
                 poi.get("type"), poi.get("address"), note, owner, created_at),
            )
            self._conn.commit()

    def list_classics(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM classics ORDER BY created_at DESC").fetchall()
        return [
            {"poiid": r["poiid"], "name": r["name"], "lat": r["lat"], "lng": r["lng"],
             "rating": r["rating"], "cost": r["cost"], "type": r["type"], "address": r["address"],
             "note": r["note"], "addedBy": r["added_by"], "createdAt": r["created_at"]}
            for r in rows
        ]

    def delete_classic(self, poiid: str, token: str, admin_token: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT added_by FROM classics WHERE poiid=?", (poiid,)).fetchone()
            if row is None:
                return False
            allowed = (admin_token and token == admin_token) or token == row["added_by"]
            if not allowed:
                return False
            self._conn.execute("DELETE FROM classics WHERE poiid=?", (poiid,))
            self._conn.commit()
        return True

    def bump_calls(self, date: str) -> int:
        with self._lock:
            self._conn.execute(
                "INSERT INTO call_log (date, count) VALUES (?, 1) "
                "ON CONFLICT(date) DO UPDATE SET count = count + 1",
                (date,),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT count FROM call_log WHERE date=?", (date,)).fetchone()
        return row["count"]

    def calls_today(self, date: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT count FROM call_log WHERE date=?", (date,)).fetchone()
        return 0 if row is None else row["count"]
