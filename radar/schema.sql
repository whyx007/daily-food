-- 美食雷达独立库（不碰 daily-food.db）
PRAGMA journal_mode=WAL;

-- 信号源（博主 / 纪录片 / 官方名录 / 私域）
CREATE TABLE IF NOT EXISTS authors (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    platform     TEXT NOT NULL,
    tier         TEXT NOT NULL,          -- doc / laozihao / zhihu / blogger / private
    followers    TEXT,
    note         TEXT,
    trust_prior  REAL NOT NULL,          -- 先验可信度 0-1
    ad_ratio     REAL,                   -- 抽检出的商业内容占比
    trust_final  REAL NOT NULL,
    sample_size  INTEGER DEFAULT 0,
    updated_at   TEXT NOT NULL
);

-- 原始线索：某人在某处说某家店
CREATE TABLE IF NOT EXISTS claims (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    poi_name      TEXT NOT NULL,
    category      TEXT,
    sub_category  TEXT,
    author_id     TEXT NOT NULL,
    url           TEXT,
    snippet       TEXT,
    published_at  TEXT,
    collected_at  TEXT NOT NULL,
    trust         REAL,                  -- 单条线索分 0-1
    signals       TEXT,                  -- 命中信号 JSON
    poiid         TEXT,                  -- 高德核验结果
    lat           REAL,
    lng           REAL,
    address       TEXT,
    verified      INTEGER DEFAULT 0,
    verify_note   TEXT,
    UNIQUE(poi_name, author_id, url)
);

-- 聚合后的店（雷达最终展示单位）
CREATE TABLE IF NOT EXISTS pois (
    poiid         TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    lat           REAL,
    lng           REAL,
    address       TEXT,
    category      TEXT,
    rating        REAL,
    cost          REAL,
    mention_count INTEGER DEFAULT 0,
    source_count  INTEGER DEFAULT 0,     -- 独立信号源数量
    consensus     REAL DEFAULT 0,        -- 维度一：重合度/稳定性 0-100
    endorsement   REAL DEFAULT 0,        -- 维度二：博主力荐 0-100
    trust         REAL DEFAULT 0,        -- 综合可信度 0-100
    reason        TEXT,                  -- 最有说服力的一句推荐理由
    authors_json  TEXT,
    detail_json   TEXT,
    first_seen    TEXT,
    last_seen     TEXT,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_poi ON claims(poiid);
CREATE INDEX IF NOT EXISTS idx_pois_trust ON pois(trust DESC);
