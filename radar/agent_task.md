# 定时任务执行手册（美食雷达刷新）

工作目录：`E:\code\deepseek\eating-test`

## 目标

每天给「西安美食雷达」补充新线索，然后重算并导出表单。**只动 `radar/` 目录，不碰 `app/`、`web/`、`daily-food.db`。**

## 步骤

1. **读现状**
   - 读 `radar/seeds/claims.json`，列出已有的 `poi_name`（避免重复）。
   - 读 `radar/README.md` 确认规则未变。

2. **找新线索**（用 web_search，每次 2–4 条查询）
   - **优先覆盖这九个品类**，哪个家数少就优先补哪个：
     牛羊肉小炒、汉民泡馍（葫芦头/三鲜煮馍）、水盆羊肉、饺子蒸饺、肉夹馍、凉皮酿皮、米线、烤肉、炒菜。
   - 搜索词模板：`西安 <品类> 本地人推荐 老店` / `西安 <品类> 苍蝇馆子 好吃 高新` /
     `西安 <品类> 长安区 韦曲 好吃`。
   - **区域优先**：用户公司在高新区、很多人住长安区。找店时优先搜「高新」「锦业路」
     「科技路」「软件新城」「郭杜」「韦曲」「长安区」这些词；其他区域的店照收，但优先级低。
   - **博主优先**：如果文章是在转述美食博主的实测（“博主@某某亲测”“抖音博主推荐”），
     优先收，并把 author 记为那个博主。
   - **只采信这些站点**：`sina.cn` / `k.sina.com.cn` / `sohu.com` / `wingantravel.com` /
     `toutiao.com`（图文页）/ `163.com`。小红书、抖音、公众号、知乎一律跳过。
   - 用 web_fetch 打开页面，**只摘原文里真实存在的句子**做 snippet，禁止自己编造评价。

3. **抽取并追加**
   - 每家店追加一条到 `radar/seeds/claims.json`：
     `poi_name`（尽量用地图上的正式名）、`category`、`sub_category`、`author_id`
     （必须是 `authors.json` / `authors_extra.json` 里已有的，没有就先加一位作者，
     `trust_prior` 按层级给：媒体 0.55–0.66、本地生活号 0.6、被引用的博主 0.62）、
     `url`、`published_at`、`snippet`（原文摘录，≤120 字）。
   - 一次最多加 5–8 条，宁缺毋滥。

4. **重算**
   ```powershell
   D:\Miniconda3\envs\daily-food\python.exe -m radar.cli seed
   D:\Miniconda3\envs\daily-food\python.exe -m radar.cli verify
   D:\Miniconda3\envs\daily-food\python.exe -m radar.cli build
   D:\Miniconda3\envs\daily-food\python.exe -m radar.cli report
   ```

5. **回报**
   - 新增几家、核验通过几家、哪几家「高德查无此店」（这类要么是小店没上地图，
     要么名字写错，下次别再重复采）。
   - 附上 `radar/out/food_table.md` 里前 5 名的变化。

## 红线

- 不编造店名、不编造评价、不用「据说」补空；
- 不采信任何带团购/返佣链接的内容；
- 单店至少要有 1 条可核验来源才进表；
- 遇到反爬（403/412/验证码）直接跳过，不要尝试绕过。
