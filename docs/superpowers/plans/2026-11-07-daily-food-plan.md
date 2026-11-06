# 每日美食随机推荐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在一台 VPS 上跑一个 Python/FastAPI 服务：按"日期 + 地理网格"确定性推荐一家附近餐厅，支持关键词搜索、共享名人堂、加权随机，左侧高德地图与导航。

**Architecture:** 单进程 FastAPI 托管静态页面与 JSON 接口；SQLite（WAL）缓存当日候选池、搜索缓存、名人堂与每日调用计数；高德 Web 服务 key 只在服务端 `.env`；左上高德 JS API 2.0，安全密钥经 Nginx 反代注入。

**Tech Stack:** Python 3.11（conda）、FastAPI、uvicorn、httpx、pydantic v2、pydantic-settings、SQLite3、pytest、pytest-asyncio、respx。

**Spec:** `docs/superpowers/specs/2026-11-07-daily-food-design.md`

## Global Constraints

- Python 3.11，conda 环境名 `daily-food`；Windows 开发、Ubuntu 部署，代码不得依赖任一平台特有路径。
- 高德 key 只从 `.env` 读取，任何日志、异常、测试输出都不打印 key 与含 key 的 URL。
- 所有测试禁止真实外呼高德（httpx 一律 `respx` mock 或注入 Fake 客户端）；单测只允许用真实 key 的手工验证脚本。
- `rating` / `cost` 缺失时必须是 `null`，不得填 `0` 或空字符串。
- 日期一律 `Asia/Shanghai`（`ZoneInfo`），格式 `YYYY-MM-DD`；外部缓存跨日即失效。
- 网格量化：`round(lat*200)/200`、`round(lng*200)/200`，格式化为三位小数的 `"lat,lng"` 字符串。
- 餐饮类型码固定 `050000`；周边搜索每页 `offset=25`，最多 3 页，取前 60 条。
- 每日外部调用上限 `DAILY_CALL_LIMIT` 默认 500；限流 20 次/分钟/IP；外部并发上限 3。
- 降级优先顺序固定：当日池 → 陈旧池（`stale=true`）→ 空态；不得返回 5xx 给前端（配置错误以 `degraded` 表达）。
- 每个任务结束必须 `git commit`，提交信息用 `feat:` / `test:` / `docs:` 前缀。

---

## 文件结构

```
environment.yml            conda 依赖
.gitignore                 忽略 .env / *.db / 缓存
.env.example               配置模板（不含真实 key）
app/__init__.py
app/config.py              Settings（.env → 强类型配置）
app/models.py              Poi / Meta / 响应模型
app/geo.py                 网格量化、haversine
app/picker.py              PRNG 种子 + 三种选法（纯函数）
app/store.py               SQLite：池、搜索缓存、名人堂、每日计数
app/amap.py                高德适配层（httpx + 归一化 + 错误码）
app/guard.py               限流、熔断判断、降级判定
app/routes.py              HTTP 接口
app/main.py                create_app + 静态托管 + lifespan
web/index.html             页面骨架（左地图右面板）
web/app.js                 前端逻辑（含 AMap JS API）
web/style.css              样式（桌面分栏 / 移动堆叠）
tests/test_config.py
tests/test_geo.py
tests/test_picker.py
tests/test_store.py
tests/test_classics.py
tests/test_amap.py
tests/test_guard.py
tests/test_routes.py
deploy/daily-food.service   systemd 单元
deploy/nginx.conf.example  Nginx 反向代理示例
README.md                  本地跑法与部署步骤
```

---

### Task 1: 项目骨架、conda 环境与配置

**Files:**
- Create: `environment.yml`, `.gitignore`, `.env.example`, `app/__init__.py`, `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings`（字段 `amap_key`, `amap_js_key`, `amap_security_code`, `default_lat`, `default_lng`, `daily_call_limit`, `radius_options`, `site_name`, `admin_token`, `db_path`, `qps`）与属性 `radius_list: list[int]`；`app.config.get_settings() -> Settings`

- [ ] **Step 1: 建环境与忽略规则**

`environment.yml`：

```yaml
name: daily-food
channels:
  - conda-forge
dependencies:
  - python=3.11
  - pip
  - pip:
      - fastapi
      - "uvicorn[standard]"
      - httpx
      - "pydantic>=2"
      - pydantic-settings
      - python-dotenv
      - pytest
      - pytest-asyncio
      - respx
```

`.gitignore`：

```
.env
*.db
*.db-wal
*.db-shm
__pycache__/
.pytest_cache/
.venv/
```

`.env.example`：

```
AMAP_KEY=
AMAP_JS_KEY=
AMAP_SECURITY_CODE=
DEFAULT_LAT=39.90923
DEFAULT_LNG=116.397428
DAILY_CALL_LIMIT=500
RADIUS_OPTIONS=500,1000,2000,3000
SITE_NAME=今天吃啥
ADMIN_TOKEN=change-me
DB_PATH=daily-food.db
QPS=3
```

- [ ] **Step 2: 写失败的配置测试**

`tests/test_config.py`：

```python
from app.config import Settings

def test_defaults_and_radius_list():
    s = Settings(amap_key="k", _env_file=None)
    assert s.default_lat == 39.90923
    assert s.daily_call_limit == 500
    assert s.radius_list == [500, 1000, 2000, 3000]

def test_radius_options_parsing_ignores_spaces():
    s = Settings(radius_options=" 800, 1500 ", _env_file=None)
    assert s.radius_list == [800, 1500]

def test_empty_env_gives_empty_key():
    s = Settings(_env_file=None)
    assert s.amap_key == ""
```

- [ ] **Step 3: 运行并确认失败**

Run: `conda activate daily-food; pytest tests/test_config.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 4: 实现 config**

`app/__init__.py` 空文件。`app/config.py`：

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    amap_key: str = ""
    amap_js_key: str = ""
    amap_security_code: str = ""
    default_lat: float = 39.90923
    default_lng: float = 116.397428
    daily_call_limit: int = 500
    radius_options: str = "500,1000,2000,3000"
    site_name: str = "今天吃啥"
    admin_token: str = ""
    db_path: str = "daily-food.db"
    qps: int = 3

    @property
    def radius_list(self) -> list[int]:
        return [int(x.strip()) for x in self.radius_options.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add environment.yml .gitignore .env.example app/ tests/
git commit -m "feat: 项目骨架与 conda 环境配置"
```

---

### Task 2: 数据模型与地理工具

**Files:**
- Create: `app/models.py`, `app/geo.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces: `Poi`（`id,name,distance,type,address,lat,lng,rating,cost,tel`，后五个可空）、`Meta`（`cachedAt: int|None, stale: bool, degraded: str|None`）、`Envelope`（`data`、`meta`）；`geo.quantize_grid(lat,lng)->str`、`geo.haversine_m(lat1,lng1,lat2,lng2)->int`

- [ ] **Step 1: 写失败测试**

`tests/test_geo.py`：

```python
from app.geo import haversine_m, quantize_grid

def test_quantize_grid_rounds_to_500m_cells():
    assert quantize_grid(39.90923, 116.397428) == "39.910,116.395"

def test_quantize_grid_same_cell_for_nearby_points():
    assert quantize_grid(39.9110, 116.3960) == quantize_grid(39.9080, 116.3940)

def test_haversine_m_about_850m_for_0_01_lng_at_39_9():
    d = haversine_m(39.90923, 116.397428, 39.90923, 116.407428)
    assert 800 <= d <= 900

def test_haversine_zero_distance():
    assert haversine_m(39.9, 116.4, 39.9, 116.4) == 0
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_geo.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.geo'`

- [ ] **Step 3: 实现模型与工具**

`app/models.py`：

```python
from pydantic import BaseModel, ConfigDict


class Poi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    distance: int | None = None
    type: str | None = None
    address: str | None = None
    lat: float
    lng: float
    rating: str | None = None
    cost: str | None = None
    tel: str | None = None


class Meta(BaseModel):
    cachedAt: int | None = None
    stale: bool = False
    degraded: str | None = None
    seed: str | None = None


class Envelope(BaseModel):
    data: object
    meta: Meta
```

`app/geo.py`：

```python
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
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_geo.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add app/models.py app/geo.py tests/test_geo.py
git commit -m "feat: POI 模型与网格/距离工具"
```

---

### Task 3: 三种选法的确定性算法

**Files:**
- Create: `app/picker.py`
- Test: `tests/test_picker.py`

**Interfaces:**
- Consumes: `app.models.Poi`
- Produces: `picker.pick(pool: Sequence[Poi], *, date: str, grid: str, mode: str = "area", radius: int = 1000, nonce: int = 0) -> tuple[Poi, str | None]`；返回 `(选中的店, degraded)`，`degraded` 为 `None` 或 `"pool_too_small"`；空池抛 `ValueError("empty_pool")`；`picker.seed_text(...) -> str`

- [ ] **Step 1: 写失败测试**

`tests/test_picker.py`：

```python
import pytest
from app.models import Poi
from app.picker import pick, seed_text


def mk(pid: str, rating: str | None, distance: int, lat: float = 39.91, lng: float = 116.40) -> Poi:
    return Poi(id=pid, name=pid, distance=distance, lat=lat, lng=lng, rating=rating)


POOL = [mk(f"p{i}", f"{3 + i % 3}.0", 100 * (i + 1)) for i in range(10)]


def test_same_inputs_same_result_1000_times():
    first, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
    for _ in range(999):
        again, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
        assert again.id == first.id


def test_different_date_changes_result():
    a, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
    b, _ = pick(POOL, date="2026-11-08", grid="39.910,116.395", mode="area", radius=1000)
    assert a.id != b.id


def test_nonce_changes_result_within_same_date():
    seen = {pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000, nonce=n)[0].id for n in range(20)}
    assert len(seen) > 1


def test_classic_mode_ignores_radius():
    a, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="classic", radius=500)
    b, _ = pick(POOL, date="2026-11-07", grid="39.910,116.395", mode="classic", radius=3000)
    assert a.id == b.id


def test_weighted_prefers_high_rating():
    pool = [mk("high", "5.0", 100), mk("low", "1.0", 100)] + [mk(f"mid{i}", "3.0", 100) for i in range(8)]
    counts = {"high": 0, "low": 0}
    for n in range(1000):
        chosen, _ = pick(pool, date="2026-11-07", grid="39.910,116.395", mode="weighted", radius=1000, nonce=n)
        if chosen.id in counts:
            counts[chosen.id] += 1
    assert counts["high"] > counts["low"] * 3


def test_missing_rating_does_not_crash_or_zero_weight():
    pool = [mk("a", None, 100), mk("b", "4.0", 100), mk("c", None, 900)]
    for n in range(50):
        pick(pool, date="2026-11-07", grid="39.910,116.395", mode="weighted", radius=1000, nonce=n)


def test_small_pool_degrades():
    pool = [mk("a", "4.0", 100), mk("b", "4.0", 200)]
    _, degraded = pick(pool, date="2026-11-07", grid="39.910,116.395", mode="area", radius=1000)
    assert degraded == "pool_too_small"


def test_empty_pool_raises():
    with pytest.raises(ValueError, match="empty_pool"):
        pick([], date="2026-11-07", grid="39.910,116.395")


def test_duplicate_ids_are_deduped():
    dup = [POOL[0], POOL[0]]
    _, degraded = pick(dup, date="2026-11-07", grid="39.910,116.395")
    assert degraded == "pool_too_small"


def test_seed_text_excludes_radius_for_classic():
    assert "500" not in seed_text("2026-11-07", "39.910,116.395", "classic", 500)
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_picker.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.picker'`

- [ ] **Step 3: 实现 picker**

`app/picker.py`：

```python
import math
import random
from typing import Sequence

from app.models import Poi


def seed_text(date: str, grid: str, mode: str, radius: int, nonce: int = 0) -> str:
    parts = [date, grid, mode]
    if mode != "classic":
        parts.append(str(radius))
    if nonce:
        parts.append(f"n{nonce}")
    return "|".join(parts)


def pick(
    pool: Sequence[Poi],
    *,
    date: str,
    grid: str,
    mode: str = "area",
    radius: int = 1000,
    nonce: int = 0,
) -> tuple[Poi, str | None]:
    items = _clean(pool)
    if not items:
        raise ValueError("empty_pool")

    seed = seed_text(date, grid, mode, radius, nonce)
    if len(items) < 3:
        rng = random.Random(seed)
        return rng.choice(items), "pool_too_small"

    rng = random.Random(seed)
    if mode == "weighted":
        median = _median_rating(items)
        weights = [_weight(p, radius, median) for p in items]
        return _weighted_choice(items, weights, rng.random()), None
    index = math.floor(rng.random() * len(items))
    return items[index], None


def _clean(pool: Sequence[Poi]) -> list[Poi]:
    seen: set[str] = set()
    out: list[Poi] = []
    for poi in pool:
        if not poi.id or not poi.name or poi.id in seen:
            continue
        seen.add(poi.id)
        out.append(poi)
    return out


def _rating(poi: Poi) -> float | None:
    try:
        value = float(poi.rating) if poi.rating not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if value is None or not 0 < value <= 5:
        return None
    return value


def _median_rating(items: Sequence[Poi]) -> float:
    ratings = sorted(r for r in (_rating(p) for p in items) if r is not None)
    if not ratings:
        return 2.5
    return ratings[len(ratings) // 2]


def _weight(poi: Poi, radius: int, median: float) -> float:
    rating = _rating(poi)
    rating_norm = (rating if rating is not None else median) / 5.0
    distance = poi.distance or 0
    distance_decay = 1.0 - min(distance / max(radius, 1), 1.0)
    score = 0.65 * rating_norm + 0.35 * distance_decay
    return score ** 2 + 1e-6


def _weighted_choice(items: Sequence[Poi], weights: Sequence[float], rnd: float) -> Poi:
    total = sum(weights)
    cursor = rnd * total
    for poi, weight in zip(items, weights):
        cursor -= weight
        if cursor <= 0:
            return poi
    return items[-1]
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_picker.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add app/picker.py tests/test_picker.py
git commit -m "feat: 三种确定性选店算法"
```

---

### Task 4: SQLite 存储（候选池、搜索缓存、每日计数）

**Files:**
- Create: `app/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: 无
- Produces: `Store(path: str)`，方法 `close()`、`get_pool(date, grid, radius, category="all") -> tuple[list[dict], int] | None`、`put_pool(date, grid, radius, category, payload: list[dict], fetched_at: int) -> None`、`get_latest_pool(grid, radius, category="all") -> tuple[list[dict], int, str] | None`、`get_search(query_key, ttl=300, now=None) -> tuple[list[dict], int] | None`、`put_search(query_key, payload, fetched_at) -> None`、`bump_calls(date) -> int`、`calls_today(date) -> int`

- [ ] **Step 1: 写失败测试**

`tests/test_store.py`：

```python
from app.store import Store


def test_pool_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.put_pool("2026-11-07", "39.910,116.395", 1000, "all", [{"id": "a"}], 100)
    got = s.get_pool("2026-11-07", "39.910,116.395", 1000)
    assert got == ([{"id": "a"}], 100)
    s.close()


def test_pool_miss_returns_none(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.get_pool("2026-11-07", "39.910,116.395", 2000) is None
    s.close()


def test_latest_pool_falls_back_to_previous_day(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.put_pool("2026-11-06", "39.910,116.395", 1000, "all", [{"id": "old"}], 50)
    got = s.get_latest_pool("39.910,116.395", 1000)
    assert got == ([{"id": "old"}], 50, "2026-11-06")
    s.close()


def test_search_cache_ttl(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.put_search("k1", [{"id": "a"}], 1000)
    assert s.get_search("k1", ttl=300, now=1100) == ([{"id": "a"}], 1000)
    assert s.get_search("k1", ttl=300, now=1400) is None
    s.close()


def test_calls_count_increments(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.calls_today("2026-11-07") == 0
    assert s.bump_calls("2026-11-07") == 1
    assert s.bump_calls("2026-11-07") == 2
    assert s.calls_today("2026-11-07") == 2
    s.close()
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_store.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.store'`

- [ ] **Step 3: 实现 store**

`app/store.py`：

```python
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
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_store.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add app/store.py tests/test_store.py
git commit -m "feat: SQLite 缓存与每日调用计数"
```

---

### Task 5: 名人堂（共享名单 CRUD）

**Files:**
- Modify: `app/store.py`
- Test: `tests/test_classics.py`

**Interfaces:**
- Produces: `Store.upsert_classic(poi: dict, added_by: str, note: str | None) -> None`、`Store.list_classics() -> list[dict]`（字典含 `poiid,name,lat,lng,rating,cost,type,address,note,addedBy,createdAt`）、`Store.delete_classic(poiid: str, token: str, admin_token: str) -> bool`

- [ ] **Step 1: 写失败测试**

`tests/test_classics.py`：

```python
from app.store import Store


def poi(pid="B001", name="老边饺子"):
    return {"id": pid, "name": name, "lat": 39.91, "lng": 116.40,
            "rating": "4.5", "cost": "35", "type": "中餐", "address": "某街"}


def test_upsert_and_list(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", "好吃")
    items = s.list_classics()
    assert len(items) == 1
    assert items[0]["poiid"] == "B001"
    assert items[0]["addedBy"] == "token-a"
    assert items[0]["note"] == "好吃"
    s.close()


def test_upsert_same_poiid_updates(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", "v1")
    s.upsert_classic(poi(name="老边饺子(新)"), "token-b", "v2")
    items = s.list_classics()
    assert len(items) == 1
    assert items[0]["name"] == "老边饺子(新)"
    assert items[0]["note"] == "v2"
    s.close()


def test_delete_requires_owner_or_admin(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", None)
    assert s.delete_classic("B001", "token-b", "secret") is False
    assert s.delete_classic("B001", "token-a", "secret") is True
    assert s.list_classics() == []
    s.close()


def test_admin_can_delete_any(tmp_path):
    # 站长把 ADMIN_TOKEN 当作 X-Client-Token 发过来
    s = Store(str(tmp_path / "t.db"))
    s.upsert_classic(poi(), "token-a", None)
    assert s.delete_classic("B001", "secret", "secret") is True
    s.close()


def test_delete_missing_returns_false(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert s.delete_classic("nope", "t", "") is False
    s.close()
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_classics.py -v`
Expected: FAIL，`AttributeError: 'Store' object has no attribute 'upsert_classic'`

- [ ] **Step 3: 实现（追加到 `app/store.py` 末尾，放在 `Store` 类内部）**

```python
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
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_classics.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add app/store.py tests/test_classics.py
git commit -m "feat: 共享名人堂的增删查"
```

---

### Task 6: 高德适配层

**Files:**
- Create: `app/amap.py`
- Test: `tests/test_amap.py`

**Interfaces:**
- Produces: `class AmapError(Exception)`（属性 `info: str`、`infocode: str`）；`class AmapClient(key: str, base: str = "https://restapi.amap.com", timeout: float = 5.0, max_concurrency: int = 3)`，方法 `async aclose()`、`async around(lat, lng, radius, keywords=None, types="050000", max_items=60) -> list[Poi]`、`async detail(poiid: str) -> Poi | None`、`async geocode(address: str) -> tuple[float, float] | None`、`async staticmap(lat, lng, zoom=14, size="600*400") -> bytes`

- [ ] **Step 1: 写失败测试**

`tests/test_amap.py`：

```python
import httpx
import pytest
import respx

from app.amap import AmapClient, AmapError

SAMPLE = {
    "status": "1", "info": "OK", "count": "2",
    "pois": [
        {"id": "B001", "name": "来今雨轩", "distance": "133", "type": "餐饮服务;中餐厅",
         "address": "某街", "location": "116.400123,39.909321",
         "biz_ext": {"rating": "4.7", "cost": "89.00"}, "tel": "010-1234"},
        {"id": "B002", "name": "小馆", "distance": "211", "type": "餐饮服务;快餐厅",
         "address": "某巷", "location": "116.398765,39.910111",
         "biz_ext": {"rating": [], "cost": []}, "tel": []},
    ],
}


@pytest.mark.asyncio
@respx.mock
async def test_around_normalizes_pois():
    respx.get("https://restapi.amap.com/v3/place/around").mock(return_value=httpx.Response(200, json=SAMPLE))
    client = AmapClient(key="k")
    pois = await client.around(39.90923, 116.397428, 1000)
    await client.aclose()
    assert [p.id for p in pois] == ["B001", "B002"]
    assert pois[0].rating == "4.7"
    assert pois[1].rating is None      # 空数组必须变成 None
    assert pois[1].cost is None
    assert pois[1].tel is None
    assert pois[0].lat == pytest.approx(39.909321)
    assert pois[0].lng == pytest.approx(116.400123)


@pytest.mark.asyncio
@respx.mock
async def test_platform_mismatch_raises_amap_error():
    respx.get("https://restapi.amap.com/v3/place/around").mock(
        return_value=httpx.Response(200, json={"status": "0", "info": "USERKEY_PLAT_NOMATCH", "infocode": "10009"})
    )
    client = AmapClient(key="k")
    with pytest.raises(AmapError) as exc:
        await client.around(39.9, 116.4, 1000)
    await client.aclose()
    assert exc.value.info == "USERKEY_PLAT_NOMATCH"
    assert exc.value.infocode == "10009"


@pytest.mark.asyncio
@respx.mock
async def test_detail_returns_poi():
    respx.get("https://restapi.amap.com/v3/place/detail").mock(return_value=httpx.Response(200, json=SAMPLE))
    client = AmapClient(key="k")
    poi = await client.detail("B001")
    await client.aclose()
    assert poi is not None and poi.name == "来今雨轩"


@pytest.mark.asyncio
@respx.mock
async def test_geocode_parses_location():
    respx.get("https://restapi.amap.com/v3/geocode/geo").mock(
        return_value=httpx.Response(200, json={"status": "1", "info": "OK",
                                              "geocodes": [{"location": "116.397428,39.90923"}]})
    )
    client = AmapClient(key="k")
    coords = await client.geocode("天安门")
    await client.aclose()
    assert coords == pytest.approx((39.90923, 116.397428))


@pytest.mark.asyncio
@respx.mock
async def test_staticmap_returns_bytes():
    respx.get("https://restapi.amap.com/v3/staticmap").mock(
        return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})
    )
    client = AmapClient(key="k")
    data = await client.staticmap(39.9, 116.4)
    await client.aclose()
    assert data == b"\x89PNG"
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_amap.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.amap'`

- [ ] **Step 3: 实现 amap.py**

```python
import asyncio

import httpx

from app.models import Poi


class AmapError(Exception):
    def __init__(self, info: str, infocode: str = "") -> None:
        super().__init__(info)
        self.info = info
        self.infocode = infocode


CONFIG_ERRORS = {"INVALID_USER_KEY", "USERKEY_PLAT_NOMATCH", "INVALID_USER_IP", "INVALID_USER_DOMAIN"}
QUOTA_ERRORS = {"DAILY_QUERY_OVER_LIMIT", "USER_DAILY_QUERY_OVER_LIMIT", "ACCESS_TOO_FREQUENT"}


def _text(value) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip()
    return text or None


def _parse_poi(raw: dict) -> Poi | None:
    location = _text(raw.get("location"))
    if not location or "," not in location:
        return None
    lng_s, lat_s = location.split(",", 1)
    try:
        lat, lng = float(lat_s), float(lng_s)
    except ValueError:
        return None
    name = _text(raw.get("name"))
    poi_id = _text(raw.get("id"))
    if not name or not poi_id:
        return None
    biz = raw.get("biz_ext") or {}
    distance = _text(raw.get("distance"))
    return Poi(
        id=poi_id,
        name=name,
        distance=int(float(distance)) if distance else None,
        type=_text(raw.get("type")),
        address=_text(raw.get("address")),
        lat=lat,
        lng=lng,
        rating=_text(biz.get("rating")),
        cost=_text(biz.get("cost")),
        tel=_text(raw.get("tel")),
    )


class AmapClient:
    def __init__(self, key: str, base: str = "https://restapi.amap.com",
                 timeout: float = 5.0, max_concurrency: int = 3) -> None:
        self._key = key
        self._base = base.rstrip("/")
        self._sem = asyncio.Semaphore(max_concurrency)
        self._http = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict) -> dict:
        params = {**params, "key": self._key}
        async with self._sem:
            for attempt in (1, 2):
                try:
                    resp = await self._http.get(f"{self._base}{path}", params=params)
                    if resp.status_code >= 500 and attempt == 1:
                        await asyncio.sleep(1.0)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except (httpx.TimeoutException, httpx.HTTPError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.0)
                    continue
        if str(data.get("status")) != "1":
            raise AmapError(str(data.get("info") or "UNKNOWN"), str(data.get("infocode") or ""))
        return data

    async def around(self, lat: float, lng: float, radius: int,
                     keywords: str | None = None, types: str = "050000",
                     max_items: int = 60) -> list[Poi]:
        out: list[Poi] = []
        for page in range(1, 4):
            params = {
                "location": f"{lng:.6f},{lat:.6f}",
                "radius": radius,
                "types": types,
                "offset": 25,
                "page": page,
                "extensions": "all",
                "sortrule": "distance",
            }
            if keywords:
                params["keywords"] = keywords
            data = await self._get("/v3/place/around", params)
            for raw in data.get("pois") or []:
                poi = _parse_poi(raw)
                if poi is not None:
                    out.append(poi)
            if len(data.get("pois") or []) < 25 or len(out) >= max_items:
                break
        return out[:max_items]

    async def detail(self, poiid: str) -> Poi | None:
        # 已用真实 key 验证：v3/place/detail?id= 可用；place/around?id= 会返回 MISSING_REQUIRED_PARAMS
        data = await self._get("/v3/place/detail", {"id": poiid, "extensions": "all"})
        for raw in data.get("pois") or []:
            poi = _parse_poi(raw)
            if poi is not None:
                return poi
        return None

    async def geocode(self, address: str) -> tuple[float, float] | None:
        data = await self._get("/v3/geocode/geo", {"address": address})
        geocodes = data.get("geocodes") or []
        if not geocodes:
            return None
        location = _text(geocodes[0].get("location"))
        if not location or "," not in location:
            return None
        lng_s, lat_s = location.split(",", 1)
        return float(lat_s), float(lng_s)

    async def staticmap(self, lat: float, lng: float, zoom: int = 14, size: str = "600*400") -> bytes:
        params = {
            "location": f"{lng:.6f},{lat:.6f}",
            "zoom": zoom,
            "size": size,
            "key": self._key,
        }
        async with self._sem:
            resp = await self._http.get(f"{self._base}/v3/staticmap", params=params)
            resp.raise_for_status()
        return resp.content
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_amap.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add app/amap.py tests/test_amap.py
git commit -m "feat: 高德适配层与错误码映射"
```

---

### Task 7: 限流与熔断守卫

**Files:**
- Create: `app/guard.py`
- Test: `tests/test_guard.py`

**Interfaces:**
- Consumes: `app.store.Store.calls_today(date)`
- Produces: `guard.RateLimiter(limit: int = 20, window: int = 60)`，方法 `allow(key: str, now: float | None = None) -> bool`；`guard.breaker_state(store, date: str, limit: int) -> str | None`（`None` 表示正常，`"warning"` 或 `"daily_limit_reached"`）

- [ ] **Step 1: 写失败测试**

`tests/test_guard.py`：

```python
from app.guard import RateLimiter, breaker_state
from app.store import Store


def test_rate_limiter_allows_20_per_minute():
    limiter = RateLimiter(limit=20, window=60)
    assert all(limiter.allow("ip", now=1000.0) for _ in range(20))
    assert limiter.allow("ip", now=1000.0) is False
    assert limiter.allow("ip", now=1061.0) is True


def test_rate_limiter_isolates_keys():
    limiter = RateLimiter(limit=2, window=60)
    assert limiter.allow("a", now=1000.0)
    assert limiter.allow("a", now=1000.0)
    assert limiter.allow("a", now=1000.0) is False
    assert limiter.allow("b", now=1000.0) is True


def test_breaker_states(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    assert breaker_state(s, "2026-11-07", 500) is None
    for _ in range(400):
        s.bump_calls("2026-11-07")
    assert breaker_state(s, "2026-11-07", 500) == "warning"
    for _ in range(100):
        s.bump_calls("2026-11-07")
    assert breaker_state(s, "2026-11-07", 500) == "daily_limit_reached"
    s.close()
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_guard.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.guard'`

- [ ] **Step 3: 实现 guard.py**

```python
import time
from collections import defaultdict, deque

from app.store import Store


class RateLimiter:
    def __init__(self, limit: int = 20, window: int = 60) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def breaker_state(store: Store, date: str, limit: int) -> str | None:
    count = store.calls_today(date)
    if count >= limit:
        return "daily_limit_reached"
    if count >= int(limit * 0.8):
        return "warning"
    return None
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_guard.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add app/guard.py tests/test_guard.py
git commit -m "feat: IP 限流与每日熔断"
```

---

### Task 8: 应用装配与 `/api/config`、`/api/today`

**Files:**
- Create: `app/routes.py`, `app/main.py`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `Settings`、`Store`、`AmapClient`、`picker.pick`、`guard`
- Produces: `app.main.create_app(settings: Settings | None = None) -> FastAPI`；应用状态挂在 `app.state.settings / store / client / limiter`；`GET /api/config`、`GET /api/today`、`GET /api/health`

- [ ] **Step 1: 写失败测试**

`tests/test_routes.py`：

```python
from datetime import date as date_cls, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.geo import quantize_grid
from app.main import create_app
from app.models import Poi
from app.routes import today_key
from app.store import Store


class FakeAmap:
    def __init__(self):
        self.calls = 0

    async def around(self, lat, lng, radius, keywords=None, types="050000", max_items=60):
        self.calls += 1
        return [Poi(id=f"B{i:03d}", name=f"店{i}", distance=100 * (i + 1), lat=lat, lng=lng,
                    rating=f"{3 + i % 3}.0", cost="40", type="中餐") for i in range(6)]

    async def detail(self, poiid):
        return Poi(id=poiid, name="详情店", lat=39.91, lng=116.40, rating="4.2")

    async def geocode(self, address):
        return (39.91, 116.40)

    async def staticmap(self, lat, lng, zoom=14, size="600*400"):
        return b"\x89PNG"

    async def aclose(self):
        pass


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(_env_file=None, db_path=str(tmp_path / "t.db")))
    app.state.client = FakeAmap()
    return TestClient(app)


def test_health(client):
    assert client.get("/api/health").json()["data"]["status"] == "ok"


def test_config_returns_radius_options(client):
    body = client.get("/api/config").json()["data"]
    assert body["radiusOptions"] == [500, 1000, 2000, 3000]
    assert body["modes"] == ["area", "classic", "weighted"]


def test_today_returns_pick_and_candidates(client):
    body = client.get("/api/today", params={"lat": 39.91, "lng": 116.40, "mode": "area"}).json()
    assert body["data"]["pick"]["id"].startswith("B")
    assert len(body["data"]["candidates"]) <= 20
    assert body["meta"]["degraded"] is None


def test_today_second_request_hits_cache(client):
    client.get("/api/today", params={"lat": 39.91, "lng": 116.40})
    client.get("/api/today", params={"lat": 39.91, "lng": 116.40})
    assert client.app.state.client.calls == 1


def test_today_rejects_bad_params(client):
    assert client.get("/api/today", params={"lat": "abc", "lng": "116.4"}).status_code == 422


def test_today_breaker_returns_stale_pool(client):
    store = client.app.state.store
    day = today_key()
    yesterday = (date_cls.fromisoformat(day) - timedelta(days=1)).isoformat()
    store.put_pool(yesterday, quantize_grid(39.91, 116.40), 1000, "all",
                   [Poi(id="B900", name="昨日店", distance=300, lat=39.91, lng=116.40,
                        rating="4.0").model_dump()], 1)
    for _ in range(501):
        store.bump_calls(day)
    resp = client.get("/api/today", params={"lat": 39.91, "lng": 116.40})
    assert resp.status_code == 200
    assert resp.json()["meta"]["stale"] is True
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_routes.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: 实现 routes 与 main**

`app/routes.py`：

```python
import hashlib
import time
from datetime import date as date_cls, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app import guard, picker
from app.amap import AmapError
from app.geo import haversine_m, quantize_grid
from app.models import Envelope, Meta, Poi

router = APIRouter()
TZ = ZoneInfo("Asia/Shanghai")


def today_key() -> str:
    return datetime.now(TZ).date().isoformat()


def _now() -> int:
    return int(time.time())


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _envelope(data, meta: Meta) -> dict:
    return Envelope(data=data, meta=meta).model_dump()


def _pois(payload: list[dict]) -> list[Poi]:
    return [Poi(**item) for item in payload]


def _classic_poi(item: dict) -> dict:
    return Poi(id=item["poiid"], name=item["name"], lat=item["lat"], lng=item["lng"],
               rating=item.get("rating"), cost=item.get("cost"),
               type=item.get("type"), address=item.get("address")).model_dump()


def _with_distance(items: list[Poi], lat: float, lng: float, keep_distance: bool) -> list[Poi]:
    out = []
    for poi in items:
        if not keep_distance or poi.distance is None:
            poi.distance = haversine_m(lat, lng, poi.lat, poi.lng)
        out.append(poi)
    return out


@router.get("/api/health")
def health():
    return {"data": {"status": "ok"}, "meta": {"stale": False, "degraded": None}}


@router.get("/api/config")
def config(request: Request):
    s = request.app.state.settings
    state = guard.breaker_state(request.app.state.store, today_key(), s.daily_call_limit)
    return _envelope({
        "siteName": s.site_name,
        "defaultCenter": {"lat": s.default_lat, "lng": s.default_lng},
        "radiusOptions": s.radius_list,
        "modes": ["area", "classic", "weighted"],
        "jsKey": s.amap_js_key,
        "securityServiceHost": request.headers.get("host", ""),
    }, Meta(degraded=None if state == "warning" else state))


@router.get("/api/today")
async def today(request: Request, lat: float, lng: float, mode: str = "area", radius: int = 1000, nonce: int = 0):
    settings = request.app.state.settings
    store = request.app.state.store
    if not request.app.state.limiter.allow(_client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "too_many_requests"}, headers={"Retry-After": "60"})
    if mode not in {"area", "classic", "weighted"}:
        return JSONResponse(status_code=400, content={"detail": "bad_mode"})
    if radius not in settings.radius_list and mode != "classic":
        radius = settings.radius_list[min(1, len(settings.radius_list) - 1)]

    grid = quantize_grid(lat, lng)
    day = today_key()
    degraded = guard.breaker_state(store, day, settings.daily_call_limit)
    if degraded == "warning":
        degraded = None

    stale = False
    pool, fetched_at = [], None
    if mode == "classic":
        pool = [_classic_poi(item) for item in store.list_classics()]
    else:
        cached = store.get_pool(day, grid, radius)
        if cached is not None:
            pool, fetched_at = cached
        elif degraded != "daily_limit_reached":
            try:
                fetched = await request.app.state.client.around(lat, lng, radius)
                store.bump_calls(day)
                payload = [p.model_dump() for p in fetched]
                store.put_pool(day, grid, radius, "all", payload, _now())
                pool, fetched_at = payload, _now()
            except AmapError as exc:
                if exc.info in {"INVALID_USER_KEY", "USERKEY_PLAT_NOMATCH"}:
                    degraded = "misconfigured"
        if not pool:
            latest = store.get_latest_pool(grid, radius)
            if latest is not None:
                pool, fetched_at, _ = latest
                stale = True

    if not pool:
        return JSONResponse(status_code=404, content={
            "data": None, "meta": {"stale": False, "degraded": degraded or "no_data"}})

    try:
        chosen, picked_degraded = picker.pick(_pois(pool), date=day, grid=grid, mode=mode,
                                              radius=radius, nonce=nonce)
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "meta": {"stale": stale,
                                                                            "degraded": "no_data"}})
    candidates = _with_distance(_pois(pool)[:20], lat, lng, keep_distance=True)
    return _envelope({
        "pick": chosen.model_dump(),
        "candidates": [p.model_dump() for p in candidates],
        "mode": mode,
    }, Meta(cachedAt=fetched_at, stale=stale, degraded=picked_degraded or degraded,
            seed=picker.seed_text(day, grid, mode, radius, nonce)))
```

`app/main.py`：

```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.amap import AmapClient
from app.config import Settings, get_settings
from app.guard import RateLimiter
from app.routes import router
from app.store import Store


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.client.aclose()
        app.state.store.close()

    app = FastAPI(title="Daily Food", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = Store(settings.db_path)
    app.state.client = AmapClient(key=settings.amap_key, max_concurrency=settings.qps)
    app.state.limiter = RateLimiter(limit=20, window=60)
    app.include_router(router)
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


app = create_app()
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_routes.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add app/routes.py app/main.py tests/test_routes.py
git commit -m "feat: 应用装配与今日推荐接口"
```

---

### Task 9: 搜索、名人堂与静态地图接口

**Files:**
- Modify: `app/routes.py`
- Test: `tests/test_routes.py`（追加用例）

**Interfaces:**
- Produces: `GET /api/search`（`q` 或 `category`，`lat`、`lng`、`radius`）、`GET /api/classics`、`POST /api/classics`、`DELETE /api/classics/{poiid}`、`GET /api/staticmap`（返回 `image/png`）

- [ ] **Step 1: 追加失败测试**

```python
def test_search_uses_cache(client):
    params = {"q": "饺子", "lat": 39.91, "lng": 116.40, "radius": 1000}
    client.get("/api/search", params=params)
    first = client.app.state.client.calls
    client.get("/api/search", params=params)
    assert client.app.state.client.calls == first


def test_search_requires_two_chars(client):
    resp = client.get("/api/search", params={"q": "饺", "lat": 39.91, "lng": 116.40})
    assert resp.status_code == 400


def test_classics_add_list_delete(client):
    r = client.post("/api/classics", json={"poiid": "B001", "note": "经典"},
                    headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    assert client.get("/api/classics").json()["data"]["items"][0]["note"] == "经典"
    r = client.delete("/api/classics/B001", headers={"X-Client-Token": "tok-b"})
    assert r.status_code == 403
    r = client.delete("/api/classics/B001", headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    assert client.get("/api/classics").json()["data"]["items"] == []


def test_classics_add_by_address(client):
    r = client.post("/api/classics", json={"name": "手填店", "address": "某街 1 号"},
                    headers={"X-Client-Token": "tok-a"})
    assert r.status_code == 200
    items = client.get("/api/classics").json()["data"]["items"]
    assert items[0]["name"] == "手填店"


def test_staticmap_returns_png(client):
    resp = client.get("/api/staticmap", params={"lat": 39.91, "lng": 116.40})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/test_routes.py -v -k "search or classics or staticmap"`
Expected: 4 failed（404）

- [ ] **Step 3: 实现接口**

追加到 `app/routes.py`：

```python
def _grid_query_key(grid: str, q: str | None, category: str | None, radius: int) -> str:
    raw = f"{grid}|{q or ''}|{category or ''}|{radius}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@router.get("/api/search")
async def search(request: Request, lat: float, lng: float, q: str | None = None,
                 category: str | None = None, radius: int = 1000):
    store = request.app.state.store
    if (q or "").strip() and len(q.strip()) < 2:
        return JSONResponse(status_code=400, content={"detail": "query_too_short"})
    if not q and not category:
        return JSONResponse(status_code=400, content={"detail": "query_required"})
    if not request.app.state.limiter.allow(_client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "too_many_requests"})

    grid = quantize_grid(lat, lng)
    key = _grid_query_key(grid, q, category, radius)
    cached = store.get_search(key, ttl=300)
    if cached is not None:
        payload, fetched_at = cached
        return _envelope({"items": payload, "cached": True}, Meta(cachedAt=fetched_at))

    day = today_key()
    if guard.breaker_state(store, day, request.app.state.settings.daily_call_limit) == "daily_limit_reached":
        return _envelope({"items": [], "cached": False}, Meta(degraded="daily_limit_reached"))

    try:
        items = await request.app.state.client.around(lat, lng, radius, keywords=(q or None),
                                                     types=category or "050000")
        store.bump_calls(day)
    except AmapError as exc:
        return _envelope({"items": [], "cached": False}, Meta(degraded=f"amap:{exc.info}"))

    payload = [p.model_dump() for p in _with_distance(items[:20], lat, lng, keep_distance=True)]
    store.put_search(key, payload, _now())
    return _envelope({"items": payload, "cached": False}, Meta(cachedAt=_now()))


@router.get("/api/classics")
def list_classics(request: Request):
    items = request.app.state.store.list_classics()
    return _envelope({"items": items}, Meta())


@router.post("/api/classics")
async def add_classic(request: Request, body: dict):
    token = request.headers.get("X-Client-Token", "")
    if not token:
        return JSONResponse(status_code=400, content={"detail": "missing_token"})
    poiid = (body or {}).get("poiid", "")
    name = (body or {}).get("name", "")
    address = (body or {}).get("address", "")

    if poiid:
        poi = await request.app.state.client.detail(poiid)
    elif name and address:
        coords = await request.app.state.client.geocode(address)
        if coords is None:
            return JSONResponse(status_code=404, content={"detail": "address_not_found"})
        lat, lng = coords
        raw = hashlib.sha1(f"{name}|{address}".encode("utf-8")).hexdigest()[:12]
        poi = Poi(id=f"addr:{raw}", name=name, lat=lat, lng=lng, address=address)
    else:
        return JSONResponse(status_code=400, content={"detail": "poiid_or_address_required"})

    if poi is None:
        return JSONResponse(status_code=404, content={"detail": "poi_not_found"})
    request.app.state.store.upsert_classic(poi.model_dump(), token, (body or {}).get("note"))
    return _envelope({"ok": True, "poiid": poi.id}, Meta())


@router.delete("/api/classics/{poiid}")
def delete_classic(request: Request, poiid: str):
    token = request.headers.get("X-Client-Token", "")
    admin = request.app.state.settings.admin_token
    ok = request.app.state.store.delete_classic(poiid, token, admin)
    if not ok:
        return JSONResponse(status_code=403, content={"detail": "forbidden"})
    return _envelope({"ok": True}, Meta())


@router.get("/api/staticmap")
async def staticmap(request: Request, lat: float, lng: float, zoom: int = 14):
    try:
        data = await request.app.state.client.staticmap(lat, lng, zoom=zoom)
    except Exception:
        return JSONResponse(status_code=503, content={"detail": "staticmap_unavailable"})
    return Response(content=data, media_type="image/png")
```

- [ ] **Step 4: 通过测试**

Run: `pytest tests/test_routes.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat: 搜索、名人堂与静态地图接口"
```

---

### Task 10: 前端页面（左地图 / 右面板）

**Files:**
- Create: `web/index.html`, `web/style.css`, `web/app.js`
- Test: 手工验收（见步骤 4）

**Interfaces:**
- Consumes: `/api/config`、`/api/today`、`/api/search`、`/api/classics`、`/api/staticmap`
- Produces: 静态页面（由 `StaticFiles` 托管在 `/`）

- [ ] **Step 1: 写页面骨架**

`web/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>今天吃啥</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<div id="layout">
  <main id="map-pane">
    <div id="map"></div>
    <div id="map-fallback" hidden></div>
  </main>
  <aside id="panel">
    <header>
      <h1 id="site-name">今天吃啥</h1>
      <form id="search-form">
        <input id="search-input" placeholder="搜饺子、面、火锅…" autocomplete="off">
        <button type="submit">搜</button>
      </form>
      <div id="chips"></div>
    </header>
    <section id="daily-card"></section>
    <section id="list"></section>
    <footer>
      <button id="btn-random">🎲 换个随机</button>
      <button id="btn-classic">⭐ 经典馆子</button>
      <div id="radius-row"></div>
    </footer>
  </aside>
</div>
<script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写样式**

`web/style.css`：

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #1f2328; }
#layout { display: grid; grid-template-columns: 1.6fr 1fr; height: 100vh; }
#map-pane { position: relative; background: #eef1f5; }
#map, #map-fallback { width: 100%; height: 100%; }
#panel { display: flex; flex-direction: column; gap: 12px; padding: 16px; overflow: hidden; border-left: 1px solid #e5e7eb; }
#panel header h1 { font-size: 18px; margin: 0 0 8px; }
#search-form { display: flex; gap: 8px; }
#search-input { flex: 1; padding: 8px 10px; border: 1px solid #d0d7de; border-radius: 8px; }
#search-form button { padding: 8px 14px; border: 0; border-radius: 8px; background: #1f2328; color: #fff; }
#chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.chip { padding: 4px 10px; border-radius: 999px; border: 1px solid #d0d7de; background: #fff; cursor: pointer; font-size: 13px; }
.chip.active { background: #1f2328; color: #fff; }
#daily-card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px; }
#daily-card .name { font-size: 20px; font-weight: 600; }
#daily-card .meta { color: #57606a; font-size: 13px; margin: 4px 0 10px; }
#daily-card .actions { display: flex; gap: 8px; }
.btn { padding: 8px 12px; border-radius: 8px; border: 1px solid #d0d7de; background: #fff; cursor: pointer; }
.btn.primary { background: #1f2328; color: #fff; border-color: #1f2328; }
#list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.item { padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 10px; cursor: pointer; }
.item.active { border-color: #1f2328; background: #f6f8fa; }
.item .sub { color: #57606a; font-size: 12px; }
#panel footer { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
#radius-row { display: flex; gap: 6px; }
.notice { color: #9a6700; font-size: 12px; }
@media (max-width: 860px) {
  #layout { grid-template-columns: 1fr; grid-template-rows: 45vh 1fr; }
  #panel { border-left: 0; border-top: 1px solid #e5e7eb; }
}
```

- [ ] **Step 3: 写前端逻辑**

`web/app.js`：

```js
const state = { config: null, lat: null, lng: null, radius: 1000, mode: 'area', nonce: 0,
                map: null, markers: [], selectedId: null, lock: false };

const $ = (sel) => document.querySelector(sel);
const token = () => {
  let t = localStorage.getItem('df-token');
  if (!t) { t = crypto.randomUUID(); localStorage.setItem('df-token', t); }
  return t;
};

async function api(path, params = {}, options = {}) {
  const qs = new URLSearchParams(params);
  const resp = await fetch(`${path}?${qs}`, { headers: { 'X-Client-Token': token() }, ...options });
  if (!resp.ok) throw new Error(`${path} ${resp.status}`);
  return resp.json();
}

function pos() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => resolve(null), { timeout: 8000 });
  });
}

function renderDaily(pick, meta) {
  const card = $('#daily-card');
  if (!pick) { card.innerHTML = '<div class="notice">今天没有可选的结果</div>'; return; }
  const rating = pick.rating ? `· ${pick.rating} 分` : '';
  const cost = pick.cost ? `· 人均 ¥${pick.cost}` : '';
  card.innerHTML = `
    <div class="name">${pick.name}</div>
    <div class="meta">${pick.distance ?? '?'}m ${rating} ${cost}</div>
    <div class="actions">
      <button class="btn primary" data-nav="${pick.id}">去这里</button>
      <button class="btn" id="btn-again">换一换</button>
    </div>`;
  card.querySelector('[data-nav]').onclick = () => navigate(pick);
  card.querySelector('#btn-again').onclick = () => { state.nonce += 1; loadToday(); };
  if (meta?.degraded) card.insertAdjacentHTML('beforeend', `<div class="notice">${meta.degraded}</div>`);
}

function renderList(items) {
  const list = $('#list');
  list.innerHTML = items.map((p) => `
    <div class="item" data-id="${p.id}">
      <div>${p.name}</div>
      <div class="sub">${p.distance ?? '?'}m ${p.rating ? p.rating + ' 分' : '暂无评分'}</div>
    </div>`).join('');
  list.querySelectorAll('.item').forEach((el) => {
    el.onclick = () => select(items.find((p) => p.id === el.dataset.id));
  });
}

function renderMarkers(items) {
  if (!state.map || !window.AMap) return;
  state.map.remove(state.markers);
  state.markers = items.slice(0, 20).map((p) => new AMap.Marker({
    position: [p.lng, p.lat], title: p.name, anchor: 'bottom-center',
    extData: p,
  }));
  state.map.add(state.markers);
  state.markers.forEach((m) => m.on('click', () => select(m.getExtData())));
}

function select(poi) {
  if (!poi) return;
  state.selectedId = poi.id;
  $('#list').querySelectorAll('.item').forEach((el) => {
    el.classList.toggle('active', el.dataset.id === poi.id);
  });
  if (state.map) state.map.setCenter([poi.lng, poi.lat]);
}

function navigate(poi) {
  if (/MicroMessenger/i.test(navigator.userAgent)) {
    alert('微信内无法唤起高德，请点右上角「在浏览器中打开」后再试。');
    return;
  }
  const to = `${poi.lng},${poi.lat},${encodeURIComponent(poi.name)}`;
  const from = state.lat ? `${state.lng},${state.lat},我的位置` : '';
  window.location.href = `https://uri.amap.com/navigation?from=${from}&to=${to}&mode=walk&callnative=1&src=${encodeURIComponent(state.config.siteName)}`;
}

async function loadToday() {
  if (state.lock) return; state.lock = true;
  try {
    const body = await api('/api/today', { lat: state.lat, lng: state.lng, mode: state.mode,
                                            radius: state.radius, nonce: state.nonce });
    renderDaily(body.data.pick, body.meta);
    renderList(body.data.candidates);
    renderMarkers(body.data.candidates);
  } catch (e) {
    $('#daily-card').innerHTML = '<div class="notice">加载失败，稍后再试</div>';
  } finally { state.lock = false; }
}

async function search(q) {
  try {
    const body = await api('/api/search', { q, lat: state.lat, lng: state.lng, radius: state.radius });
    renderList(body.data.items);
    renderMarkers(body.data.items);
  } catch (e) { /* 保持原列表 */ }
}

function initMap() {
  if (!window.AMap) {
    $('#map').hidden = true; $('#map-fallback').hidden = false;
    $('#map-fallback').innerHTML = `<img src="/api/staticmap?lat=${state.lat}&lng=${state.lng}" style="width:100%;height:100%;object-fit:cover">`;
    return;
  }
  state.map = new AMap.Map('map', { center: [state.lng, state.lat], zoom: 15, viewMode: '2D' });
}

async function boot() {
  const cfg = (await api('/api/config')).data;
  state.config = cfg;
  $('#site-name').textContent = cfg.siteName;
  const geo = await pos();
  state.lat = geo?.lat ?? cfg.defaultCenter.lat;
  state.lng = geo?.lng ?? cfg.defaultCenter.lng;

  if (cfg.jsKey) {
    window._AMapSecurityConfig = { serviceHost: cfg.securityServiceHost || location.host };
    await new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = `https://webapi.amap.com/maps?v=2.0&key=${cfg.jsKey}`;
      s.onload = resolve; s.onerror = resolve;
      document.head.appendChild(s);
    });
  }
  initMap();

  const chips = [['饺子', '饺子'], ['面', '面'], ['火锅', '火锅'], ['快餐', '快餐']];
  $('#chips').innerHTML = chips.map(([label, q]) => `<span class="chip" data-q="${q}">${label}</span>`).join('');
  $('#chips').querySelectorAll('.chip').forEach((el) => {
    el.onclick = () => { el.classList.add('active'); search(el.dataset.q); };
  });

  $('#search-form').onsubmit = (e) => { e.preventDefault();
    const v = $('#search-input').value.trim(); if (v.length >= 2) search(v); };

  $('#btn-random').onclick = () => { state.mode = 'area'; state.nonce += 1; loadToday(); };
  $('#btn-classic').onclick = () => { state.mode = 'classic'; state.nonce += 1; loadToday(); };

  $('#radius-row').innerHTML = cfg.radiusOptions.map((r) =>
    `<span class="chip ${r === state.radius ? 'active' : ''}" data-r="${r}">${r}m</span>`).join('');
  $('#radius-row').querySelectorAll('.chip').forEach((el) => {
    el.onclick = () => {
      state.radius = Number(el.dataset.r);
      $('#radius-row').querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
      el.classList.add('active');
      loadToday();
    };
  });

  loadToday();
}

boot().catch(() => { $('#daily-card').innerHTML = '<div class="notice">初始化失败</div>'; });
```

- [ ] **Step 4: 手工验收**

Run: `uvicorn app.main:app --reload --port 8000`，浏览器打开 `http://127.0.0.1:8000`（需 `.env` 里有可用的 Web 服务 key；无 JS key 时左侧自动走静态地图）。
Expected：卡片出现推荐 → 点候选地图跳转 → 点「去这里」唤起导航。若无 JS key，`#map-fallback` 显示静态图。

- [ ] **Step 5: 提交**

```bash
git add web/
git commit -m "feat: 左地图右面板的前端页面"
```

---

### Task 11: 部署文件、README 与验收

**Files:**
- Create: `deploy/daily-food.service`, `deploy/nginx.conf.example`, `README.md`
- Modify: `.env.example`（确认与 `Settings` 字段一致）

**Interfaces:**
- Produces: Ubuntu 部署步骤与 systemd/Nginx 配置；本地运行说明

- [ ] **Step 1: 写部署文件**

`deploy/daily-food.service`：

```ini
[Unit]
Description=Daily Food API
After=network.target

[Service]
Type=simple
User=dailyfood
WorkingDirectory=/opt/daily-food
EnvironmentFile=/opt/daily-food/.env
ExecStart=/opt/daily-food/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`deploy/nginx.conf.example`：

```nginx
server {
  listen 80;
  server_name dailyfood.example.com;

  location /_AMapService/ {
    set $args "$args&jscode=REPLACE_WITH_SECURITY_CODE";
    proxy_pass https://restapi.amap.com/;
  }

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
}
```

- [ ] **Step 2: 写 README**

`README.md`：

````markdown
# 今天吃啥

每日随机选一家附近餐厅，支持关键词搜索与共享名人堂。设计文档见 `docs/superpowers/specs/2026-11-07-daily-food-design.md`。

## 本地运行（Windows）

```powershell
conda env create -f environment.yml
conda activate daily-food
copy .env.example .env   # 填入 AMAP_KEY
uvicorn app.main:app --reload --port 8000
```

打开 http://127.0.0.1:8000 。没有 `AMAP_JS_KEY` 时左栏自动降级为静态地图。

## 测试

```powershell
pytest -v
```

测试全部 mock，不会消耗高德额度。真实 key 只允许手工验证：

```powershell
curl "https://restapi.amap.com/v3/place/text?key=$env:AMAP_KEY&keywords=饺子&city=110000"
```

## Ubuntu 部署

```bash
conda env create -f environment.yml
sudo mkdir -p /opt/daily-food
# 拷贝代码与 .env 到 /opt/daily-food
sudo cp deploy/daily-food.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now daily-food
```

Nginx 配置见 `deploy/nginx.conf.example`，把 `REPLACE_WITH_SECURITY_CODE` 换成 JS API 安全密钥。

## 额度保护

- 每日外呼上限 `DAILY_CALL_LIMIT`（默认 500），超限只读缓存；
- 搜索缓存 5 分钟，周边池按「日期 + 网格 + 半径」缓存到次日；
- 每 IP 20 次/分钟。
````

- [ ] **Step 3: 全量测试**

Run: `pytest -v`
Expected: 全部通过（config 3 + geo 4 + picker 10 + store 5 + classics 5 + amap 5 + guard 3 + routes 10 = 45 passed）

- [ ] **Step 4: 手工验收（真实 key）**

Fill `.env` 的 `AMAP_KEY`，启动服务，逐条确认：今日推荐出现 → 换一换变化 → 搜索「饺子」出结果 → 名人堂录入/删除 → 导航跳转 → 断网后仍返回缓存或空态而非 500。

- [ ] **Step 5: 提交**

```bash
git add deploy/ README.md .env.example
git commit -m "docs: 部署文件与运行说明"
```
