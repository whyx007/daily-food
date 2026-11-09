# 西安美食雷达（独立模块）

不依赖 `daily-food.db`，自己一套 SQLite + 采集 + 打分 + 表单导出。

## 目录

```
radar/
  schema.sql        三张表：authors / claims / pois
  db.py             SQLite 访问
  adfilter.py       反软广规则（可解释，命中即记）
  amap_verify.py    高德核验：店名 -> 真实 POI（查不到 = 强降权）
  consolidate.py    两个维度打分 + 聚合
  export.py         导出 Markdown / CSV / HTML
  cli.py            命令行
  seeds/
    authors.json      信号源（博主/纪录片/老字号/私域）
    authors_extra.json 追加的媒体源
    claims.json       线索（店名 + 来源 + 原文片段 + 日期）
  out/
    food_table.md     最终表单（Markdown）
    food_table.csv    最终表单（Excel 可开）
    index.html        可筛选的网页视图
```

## 两个评分维度

| 维度 | 含义 | 怎么算 |
|---|---|---|
| **重合度 / 稳定性** `consensus` | 有多少独立信号源认同这家店、认同得多久 | 各来源按层级加权求和（私域 1.0 / 纪录片 0.9 / 老字号 0.85 / 知乎 0.7 / 媒体 0.6 / 博主 0.5），再叠加「提及时间跨度 ≥半年 / ≥一年」加成 |
| **博主力荐** `endorsement` | 美食博主层级对它的推荐强度 | 取博主线索的最高分 ×100，多博主 +10/个，出现「力荐/必吃/吃了N年」等措辞再 +8 |

综合可信度 = `0.6×重合度 + 0.4×博主力荐 + 10（高德核验加成）`，满分 100。

## 反软广规则（`adfilter.py`）

扣分：挂团购/返佣链接 −50、导流/合作 −30、自述广告 −15、套话密度高 −30、绝对化表述 −15、只谈氛围 −10。
加分：提到店主/经营年限 +20、有价格分量细节 +20、主动提缺点 +15、提时段排队 +10、本地人身份 +15。

每条线索命中的信号都存进 `claims.signals`，可以逐条复盘「为什么这店分低」。

## 常用命令

```powershell
python -m radar.cli init      # 建库
python -m radar.cli seed      # 导入 seeds/*.json
python -m radar.cli verify    # 高德核验（自动限速 + 限流重试）
python -m radar.cli build     # 打分 + 聚合 + 导出三种格式
python -m radar.cli report    # 命令行看结果
python -m radar.cli all       # 一把梭
```

## 加新线索

1. 在 `radar/seeds/claims.json` 末尾追加一条：
   ```json
   {"poi_name":"店名","category":"泡馍","sub_category":"小炒泡馍",
    "author_id":"sohu_mixian","url":"https://…","published_at":"2025-10-09",
    "snippet":"原文里关于这家店的那句话（越具体越好）"}
   ```
2. `author_id` 必须是 `seeds/authors.json` 或 `authors_extra.json` 里已有的 id，否则会被跳过；
3. 重跑 `seed → verify → build`。

## 关于「全自动」的现实边界

实测可自动抓取的只有 **新浪 / 搜狐 / 永安旅遊 / 头条图文类**；小红书、抖音、微信公众号、知乎都会被风控拦住（验证码 / 登录态 / 412）。所以：
- **脚本**负责：高德核验、打分、聚合、导出（完全自动）；
- **agent**负责：用 web_search 找新文章 → 读页面 → 抽取店名和原文片段 → 追加进 `claims.json`（半自动，人工可复核）。

定时任务每天跑一次，执行手册见 `agent_task.md`。
