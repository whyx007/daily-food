# 定时任务执行手册（美食雷达刷新）

本文件是**可移植**的：不含任何机器专属路径。换一台机器 / 换一个 Harness，只要 clone 本仓库，按本文件跑即可。

## 0. 先确定解释器（每个环境不一样，不要照抄别人的路径）

按顺序试，能用第一个就用它：

```bash
python -m radar.cli report     # 已在 PATH 里的 python
python3 -m radar.cli report    # Linux / macOS
```

Windows 上若用的是 conda 环境，先用 `conda activate daily-food`，或直接把该环境的 python 写进命令。
**判断标准**：`python -c "import httpx, pydantic"` 不报错即可。缺包就 `pip install -r requirements.txt`（httpx + 后端依赖已够雷达用）。

## 1. 目标

每天给「西安美食雷达」补充新线索，然后重算并导出表单。

**只动 `radar/` 目录，不碰 `app/`、`web/`、`daily-food.db`。**

## 2. 步骤

### 2.1 读现状
- 读 `radar/seeds/claims.json`，列出已有的 `poi_name`（避免重复）；
- 读 `radar/README.md` 确认规则未变。

### 2.2 找新线索（web_search，每次 2–4 条查询）

**十个品类，哪个家数少就补哪个**：
牛羊肉小炒、汉民泡馍（葫芦头/三鲜煮馍/粉汤羊血）、水盆羊肉、饺子蒸饺、肉夹馍、
凉皮酿皮（含秦镇米皮）、米线、**面**（biangbiang/油泼/臊子/牛肉面）、烤肉、炒菜。

- 搜索词模板：`西安 <品类> 本地人推荐 老店` / `西安 <品类> 苍蝇馆子 好吃 高新` /
  `西安 <品类> 长安区 韦曲 好吃`。
- **区域优先**：高新区（锦业路/科技路/唐延路/软件新城/鱼化寨/丈八）＋长安区（韦曲/郭杜/航天基地）。
  其他区域的店照收，但优先级低。
- **博主优先**：文章里若在转述美食博主实测（“博主@某某亲测”“抖音博主推荐”），优先收，
  author 记给那个博主。
- **可采信站点**（能抓到正文的）：
  `sina.cn` / `k.sina.com.cn` / `sohu.com` / `163.com` / `thepaper.cn` /
  `wingontravel.com` / `you.ctrip.com`（携程美食页，常有真实到店点评）/ `post.smzdm.com`。
- **一律跳过**（有风控，抓不到正文，别浪费请求）：
  小红书、抖音、微信公众号、知乎、百度百科、`toutiao.com`。
- 用 web_fetch 打开页面，**只摘原文里真实存在的句子**做 snippet，禁止编造。

### 2.3 抽取并追加

每家店追加一条到 `radar/seeds/claims.json`：

```json
{"poi_name":"店名（尽量用地图正式名）","category":"泡馍","sub_category":"小炒泡馍",
 "author_id":"已有作者id","url":"页面URL","published_at":"YYYY-MM-DD",
 "snippet":"原文原句（≤120 字）"}
```

- `author_id` 必须已存在于 `seeds/authors.json` 或 `authors_extra.json`；没有就先加一位作者，
  `trust_prior` 按层级给：官方号 0.62–0.66、本地媒体 0.55–0.60、UGC 点评 0.42–0.50、博主 0.50–0.65。
- 一次最多加 5–8 条，宁缺毋滥。
- 也可以用 `python -m radar.merge <json文件>` 批量并入（自动去重、校验 author_id）。

### 2.4 重算

```bash
python -m radar.cli seed      # 导入 seeds/*.json
python -m radar.cli verify    # 高德核验（自动限速 + 限流重试）
python -m radar.cli build     # 打分 + 聚合 + 导出 md/csv/html
python -m radar.cli report    # 命令行看结果
```

一条命令跑完：`python -m radar.cli all`

> `verify` 需要 `AMAP_KEY`（高德 Web 服务 Key）。在仓库根目录 `.env` 里写 `AMAP_KEY=...`，
> 或设环境变量。**没有 Key 就跳过 verify**，`build` 仍能出表（只是少核验加分）。

### 2.5 回报
- 新增几家、核验通过几家；
- 哪几家「高德查无此店」（小店没上地图 or 名字写错，下次别重复采）；
- `radar/out/food_table.md` 里前 5 名的变化。

## 3. 红线

- 不编造店名、不编造评价、不用「据说」补空；
- 不采信任何带团购/返佣链接的内容；
- snippet 必须是页面原句，可截断但不可改写；
- 遇到反爬（403/412/验证码）直接跳过，不要尝试绕过。
