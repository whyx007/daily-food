# 每日美食随机推荐 —— 设计文档

- 日期：2026-11-07
- 状态：待评审
- 部署目标：先 Windows 本机开发验证，后迁 Ubuntu 服务器
- 后端语言：Python（conda 环境）

## 1. 背景与目标

朋友们每天纠结"吃哪家"。做一个开箱即用的页面：打开就能看到"今天这顿"推荐哪家店，一键导航过去；也能按关键词（饺子、面、火锅）搜附近，或从大家共同维护的"名人堂"里随机。

目标：

1. 每天同一区域、同一模式，推荐结果确定不变（刷新不跳），但"换一换"可以在已缓存的候选池内换；
2. 几十人共用一台服务器时，外部地图 API 的调用量被网格化缓存和每日熔断兜住；
3. 前端只做展示与交互，不接触任何地图 key。

## 2. 范围

**做：**

- 区域随机（距离可选 500m / 1km / 2km / 3km，完全均匀）；
- 名人堂随机（共享名单，人人可录入，按添加者匿名标识删除）；
- 加权随机（按"评分 + 距离"算分，概率倾斜给高分店）；
- 关键词搜索附近店铺（周边搜索 + 关键词，不是全城搜索）；
- 左侧高德 JS API 地图 + 右侧操作面板，点列表联动地图，导航唤起高德；
- 每日候选池缓存、限流、每日调用熔断、降级。

**不做：**

- 账号体系、登录、密码（用浏览器匿名 token 区分添加者）；
- 大众点评/美团数据（无公开接口，抓取违规）；
- 页面内逐向导航（网页做不到，唤起 App 即可）；
- 多城市切换、偏好学习、收藏打分、外卖下单；
- 自然语言对话式检索（第一期用关键词 + 快捷词片）。

## 3. 总体架构

```
浏览器（静态页面 + AMap JS API 2.0）
   │  GET /api/today /api/search /api/classics
   ▼
FastAPI (uvicorn，单进程，同进程托管静态资源)
   ├─ picker.py    纯函数：seed → 确定性/加权抽样
   ├─ amap.py      高德适配层（httpx），归一化 POI
   ├─ store.py     SQLite（WAL）：池缓存、搜索缓存、名人堂、调用计数
   ├─ guard.py     限流、每日熔断、降级
   └─ routes.py    HTTP 接口
   │
   ▼
高德 Web 服务 API（key 仅服务端 .env）
   ▲
Nginx（Ubuntu）→ /_AMapService/ 反代，注入 JS API 安全密钥
```

一次 `/api/today` 的路径：坐标 → 网格（约 500m）→ 查当日池 → 未命中调一次高德周边搜索并写缓存 → 选店 → 返回。

## 4. 外部数据源（高德）

| 能力 | 接口 | 用途 |
|---|---|---|
| 周边搜索 | `GET https://restapi.amap.com/v3/place/around` | 主体：`location`、`radius`、`types=050000`、可选 `keywords`、`offset=25`、`page` 翻页至 60 条 |
| 关键词搜索 | 同上 + `keywords`（不另用 `place/text`） | 保证结果落在用户半径内 |
| POI 详情 | 同上 + `id=` | 录入名人堂时服务端回查补全字段 |
| 静态地图 | `GET https://restapi.amap.com/v3/staticmap` | JS API 加载失败时的左侧兜底图 |
| 地理编码 | `GET https://restapi.amap.com/v3/geocode/geo` | 手填地址录入名人堂 |
| 导航唤起 | `https://uri.amap.com/navigation?...&mode=walk&callnative=1` | 前端按钮，不需要 key |
| 地图展示 | AMap JS API 2.0 | 左栏地图、标记、信息窗、可选步行路线 |

字段映射（统一为内部 POI 模型）：

| 高德字段 | 内部字段 | 备注 |
|---|---|---|
| `id` | `id` | poiid，名人堂主键 |
| `name` | `name` | — |
| `distance` | `distance` | 米，整数；缺失时按坐标计算 |
| `type` | `type` | 分号分隔的分类字符串 |
| `address` | `address` | — |
| `location` | `lat` / `lng` | "经度,纬度" 拆开 |
| `biz_ext.rating` | `rating` | 字符串，缺失为 `null` |
| `biz_ext.cost` | `cost` | 字符串，缺失为 `null` |
| `tel` | `tel` | 缺失为 `null` |

**关键约定**：`rating` / `cost` 缺失时保持 `null`，绝不填 0 或空串；坐标保留 6 位小数。

## 5. 数据模型（SQLite，WAL 模式）

```sql
CREATE TABLE area_pool (
  date TEXT NOT NULL, grid TEXT NOT NULL, radius INTEGER NOT NULL,
  category TEXT NOT NULL DEFAULT 'all',
  payload TEXT NOT NULL, fetched_at INTEGER NOT NULL,
  PRIMARY KEY (date, grid, radius, category)
);

CREATE TABLE search_cache (
  query_key TEXT PRIMARY KEY,        -- sha1(grid|q|radius)
  payload TEXT NOT NULL, fetched_at INTEGER NOT NULL
);

CREATE TABLE classics (
  poiid TEXT PRIMARY KEY, name TEXT NOT NULL,
  lat REAL NOT NULL, lng REAL NOT NULL,
  rating TEXT, cost TEXT, type TEXT, address TEXT,
  note TEXT, added_by TEXT NOT NULL, created_at INTEGER NOT NULL
);

CREATE TABLE call_log (
  date TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0
);
```

- `grid`：`round(lat, 2位小数) + ',' + round(lng, 2位小数)` 的 0.005° 量化（约 500m）；
- `area_pool` 的 `date` 为 `Asia/Shanghai` 的 `YYYY-MM-DD`，跨日自然失效，不需要额外清理任务；
- `search_cache` TTL 5 分钟；
- 过期行按需删除即可，不做后台 GC。

## 6. HTTP 接口

统一返回 `{ "data": ..., "meta": { "cachedAt": ..., "stale": bool, "degraded": null|string } }`。

### GET /api/config

```json
{ "siteName": "今天吃啥", "defaultCenter": {"lat": 39.90923, "lng": 116.397428},
  "radiusOptions": [500, 1000, 2000, 3000], "modes": ["area", "classic", "weighted"],
  "degraded": null }
```

### GET /api/today

参数：`lat`、`lng`（必填，浮点）、`mode`（`area|classic|weighted`，默认 `area`）、`radius`（默认 1000）、`nonce`（换一换时递增）。

```json
{ "data": {
    "pick": { "id": "B00057...", "name": "老边饺子", "distance": 420,
              "type": "餐饮服务;中餐厅;东北菜", "address": "…",
              "lat": 39.91, "lng": 116.40, "rating": "4.5", "cost": "35", "tel": "…" },
    "candidates": [ /* 同上结构，最多 20 条 */ ],
    "mode": "weighted", "seed": "2026-11-07|39.91,116.40|1000|weighted" },
  "meta": { "cachedAt": 1762440000, "stale": false, "degraded": null } }
```

### GET /api/search

参数：`q`（≥2 字符）或 `category`（餐饮子类码）、`lat`、`lng`、`radius`。返回 `items`（最多 20 条）+ `meta`。

### GET /api/classics

返回 `items`（POI 结构 + `note`、`addedBy`），按 `created_at` 倒序。

### POST /api/classics

请求头 `X-Client-Token`（前端 localStorage 生成的 UUID）。body：`{"poiid": "...", "note": "可选"}`。
服务端用 `poiid` 回查一次 POI 详情再落库，防止伪造；同 `poiid` 重复录入视为更新备注。

### DELETE /api/classics/{poiid}

`X-Client-Token` 必须等于记录里的 `added_by`，或等于 `.env` 里的 `ADMIN_TOKEN`；否则 403。

**错误约定**：参数错误 400；限流 429 + `Retry-After`；外部额度耗尽不改状态码，用 `meta.degraded` 表达。

## 7. 三种选取算法（`picker.py`，纯函数）

公共前提：候选池先按 `id` 去重，丢弃无 `name` / 无坐标的条目。

**PRNG**：`seed = fnv1a32(f"{date}|{grid}|{radius}|{mode}" + (f"|n{nonce}" if nonce else ""))`，用 mulberry32 生成确定性序列。

1. **area（区域均匀）**：`index = floor(prng() * len(pool))`。
2. **classic（名人堂均匀）**：池为 `classics` 全量，不按距离过滤；`seed` 用 `date|grid|classic|nonce`。结果带距离，>3km 时前端提示"较远"。
3. **weighted（评分加权）**：
   - `rating_norm = rating / 5.0`；`rating` 缺失时取池内已评分店的**中位数**；
   - `distance_decay = 1 - min(distance / radius, 1.0)`；
   - `score = 0.65 * rating_norm + 0.35 * distance_decay`；`weight = score**2 + 1e-6`；
   - 累积权重 + `prng()` 抽样。

**边界**：池 < 3 家时退化为均匀随机，`meta.degraded = "pool_too_small"`；空池返回 404 + 明确文案。

## 8. 额度保护、错误处理与降级

- `AmapClient`：超时 5s，仅对超时/5xx 重试 1 次，全局并发信号量 3；日志不打印 key 与完整 URL。
- 业务错误码处理：

| 错误码 | 处理 |
|---|---|
| `INVALID_USER_KEY` / `USERKEY_PLAT_NOMATCH` | 配置错误，ERROR 日志 + `degraded: "misconfigured"`，不重试、不计数 |
| `DAILY_QUERY_OVER_LIMIT` / `USER_DAILY_QUERY_OVER_LIMIT` | 熔断，转只读缓存 |
| `CUQPS_HAS_EXCEEDED_THE_LIMIT` | 退避 1s 重试一次，仍失败走降级 |

- 熔断：`call_log` 当日计数，阈值 `DAILY_CALL_LIMIT=500`；80% 写 WARN；达阈值后外呼接口一律返回缓存 + `degraded: "daily_limit_reached"`。
- 降级顺序：当日池 → 陈旧池（`stale: true` + `cachedAt`）→ 空态提示。任何情况不返回 500。
- 限流：按 IP 令牌桶 20 次/分钟，超限 429 + `Retry-After`。

## 9. 前端

**布局**：桌面左右分栏（左 60% 地图，右 40% 面板）；移动端上下堆叠（地图 45vh，面板可滑动）。

**面板内容**：顶部搜索框 + 快捷词片（饺子 / 面 / 火锅 / 随机）；"今日这顿"大卡片（店名、距离、评分、`[去这里]`、`[换一换]`）；候选列表（滚动）；名人堂入口。

**地图联动**：右侧点候选 → `setCenter` + 高亮 marker + InfoWindow；点 marker → 列表滚到该项；点空白 → 取消选中。只渲染当前可见的 10–20 个 marker。步行路线用 `AMap.Walking` 插件按需加载，只画选中店一次。

**导航**：`https://uri.amap.com/navigation?from=当前坐标&to=店铺坐标,店名&mode=walk&callnative=1&src=站点名`；UA 含 `MicroMessenger` 时替换为"请用浏览器打开"提示。

**密钥**：`window._AMapSecurityConfig = { serviceHost: '站点域名' }`，前端只带 JS API key；`securityJsCode` 由 Nginx 注入：

```nginx
location /_AMapService/ {
  set $args "$args&jscode=<安全密钥>";
  proxy_pass https://restapi.amap.com/;
}
```

**兜底**：JS API 加载失败 → 左侧换成 `/api/staticmap` 返回的图片，导航按钮保持可用。

## 10. 技术栈与运行环境

`environment.yml`（Windows 与 Ubuntu 通用）：

```yaml
name: daily-food
dependencies:
  - python=3.11
  - pip
  - pip:
      - fastapi
      - "uvicorn[standard]"
      - httpx
      - "pydantic>=2"
      - python-dotenv
      - pytest
      - pytest-asyncio
      - respx
```

- 目录：`app/`（`main.py`、`routes.py`、`amap.py`、`picker.py`、`store.py`、`guard.py`）、`web/`（静态页面）、`tests/`、`docs/`；
- Windows：`conda activate daily-food` + `uvicorn app.main:app --reload --port 8000`；
- Ubuntu：systemd 托管 `uvicorn app.main:app --host 127.0.0.1 --port 8000`，Nginx 反代 + `/_AMapService/` 注入；
- 时区统一 `ZoneInfo("Asia/Shanghai")`；路径一律 `pathlib`。

## 11. 测试与验收

**单元测试（不打真实接口）**

- 确定性：同输入调用 1000 次结果恒等；
- `nonce` 递增能换到不同店；
- 加权：评分高的店被选概率显著更高，且低分店仍可达（固定 PRNG 抽样 1 万次统计）；
- 缺失 `rating` 用中位数、不出现除零；
- 池 < 3 家触发 `pool_too_small`。

**集成测试（`respx` mock httpx）**

- 缓存命中不产生第二次外部调用；跨日后失效；
- 熔断：第 N 次调用返回 `degraded: "daily_limit_reached"`；
- 错误码分类：平台不匹配不计数，额度耗尽触发熔断；
- 名人堂增删权限：非添加者删除返回 403。

**手工验收清单**

- Windows 本机跑通：搜索 → 选中 → 地图定位 → 导航跳转；
- 移动端布局与微信 UA 提示；
- 断网时降级到陈旧池/空态；
- Ubuntu 上 systemd + Nginx 部署后同一流程复跑。

## 12. 配置项（`.env`，不提交）

```
AMAP_KEY=…              # Web 服务 key（服务端）
AMAP_JS_KEY=…           # Web端(JS API) key（前端可见）
AMAP_SECURITY_CODE=…    # 仅 Nginx 用
DEFAULT_LAT=…
DEFAULT_LNG=…
DAILY_CALL_LIMIT=500
RADIUS_OPTIONS=500,1000,2000,3000
SITE_NAME=今天吃啥
ADMIN_TOKEN=…
```

## 13. 风险与待办

1. **key 平台不匹配（阻塞验证）**：现有 `daily-food-web` 返回 `USERKEY_PLAT_NOMATCH`，需在控制台新建「Web 服务」平台 key；同时该 key 已在聊天中泄露，应删除。JS API 另需「Web端(JS API)」key + 安全密钥。
2. **评分覆盖率未知**：因 key 无效未能探针验证；算法已用中位数兜底，若覆盖率过低（<20%），加权随机退化为距离优先，需在实现时打印覆盖率日志。
3. **合规**：朋友小范围共用可视为个人非商业使用；若公开传播或商用，需办理高德商业授权，并按要求标注数据来源。
4. **微信内唤起**：`callnative` 在微信/QQ 内置浏览器大概率失败，已用提示文案兜底。
5. **SQLite 并发**：几十人低并发 + WAL 足够；若后续写入变频繁，再评估迁移。
