# 今天吃啥（daily-food）

每天随机推荐一家附近餐厅：左侧高德地图 + 导航，右侧搜索、候选列表、共享名人堂。

交互要点：

- 三个模式按钮（区域随机 / 经典馆子 / 高分优先）有选中态与按压反馈；
- 点「高分优先」会弹出评分档位菜单（不限 / 4.5+ / 4+ / 3.5+），选中档位后按钮上会显示当前过滤值；
- **距离档位**严格生效：切换 500m/1km/2km/3km 后当前视图（推荐或搜索结果）按新半径重新拉取；半径内没有结果时不会偷偷放宽，而是给出「放宽到 5 公里搜」按钮；经典馆子模式下距离档位置灰（该模式不按距离过滤）；
- **点击地图任意位置** → 弹出商家信息卡：名称、类型、地址、评分、人均、电话、坐标，并可直接「去这里 / 加入经典馆子 / 设为出发点」；点位没有对应商家档案时会让你确认店名后按坐标录入；
- **地图顶部搜索框** → 输入商家关键词（饺子、星巴克、火锅…）搜索附近，**第一个结果自动成为首栏推荐店家**（地图标记、卡片、列表高亮同步），不用再点一次；
- **右键地图** → 就地弹出菜单：设为出发点（蓝点标记，距离与导航起点随之改变），或加入经典馆子——右键落在店铺标记上会直接带出店名，落在空白处会先逆地理编码识别该处最近的餐厅并预填店名（可编辑后再确认）；
- **出发点**显示在右侧栏顶部，用逆地理编码换成人能读的地名（优先小区/园区/商圈，其次「XX附近」，最后街道+路名），坐标与来源作副标题；点「用我的定位」可重置为当前位置。地名缓存 30 天，不额外消耗额度；
- **电话**：高德有收录的商家会在卡片里显示 📞 号码（可点击拨号），列表项也会带电话小图标；约四成商家有号码，没有的不显示；
- **点击列表项** → 首栏卡片切换成该店（地址、坐标、电话与三个按钮）；
- **地图默认不铺标记**：只有右侧列表选中某家时，才在地图上落一个标记并把视野移过去；
- **位置校正**：选中某家后，右键地图上它真正的位置，选「📌 把「店名」的位置校正到这里」，之后列表距离、地图标记、导航都用校正后的坐标（存 `poi_fixes` 表；撤销可 `DELETE /api/fixes/{poiid}`）；
- **右键右侧列表项** → 直接加入经典馆子；加入成功后右侧列表会立即切到「经典馆子」并高亮新增的那家，不用手动刷新；
- 点「去这里」唤起高德导航，微信内会提示换浏览器打开。
设计文档见 [docs/superpowers/specs/2026-11-07-daily-food-design.md](docs/superpowers/specs/2026-11-07-daily-food-design.md)，
实现计划见 [docs/superpowers/plans/2026-11-07-daily-food-plan.md](docs/superpowers/plans/2026-11-07-daily-food-plan.md)。

## 经典馆子（名人堂）的数据怎么留

名人堂存在 SQLite 里（`daily-food.db`，已被 `.gitignore` 排除），所以**默认不进 git**。要让名单跟着仓库走：

```powershell
# 导出当前数据库里的名人堂到 data/classics.json
python scripts/export_classics.py
git add data/classics.json && git commit -m "data: 更新经典馆子名单"
```

服务启动时，如果数据库里**一条名人堂都没有**，会自动从 `data/classics.json` 导入。所以换机器 / 部署到 Ubuntu 时，clone 下来第一次启动就有名单；之后本地增删不会自动写回这个文件，需要重新导出才同步（避免本地操作覆盖仓库版本）。想禁用自动导入就把 `.env` 里的 `SEED_FILE` 设为空。

## 本地运行（Windows）

```powershell
# 已安装 conda 的前提下
conda env create -f environment.yml
conda activate daily-food
copy .env.example .env   # 填入 AMAP_KEY（平台必须是「Web 服务」）
uvicorn app.main:app --reload --port 8000
```

打开 http://127.0.0.1:8000 。

- 没有 `AMAP_JS_KEY` 时，左栏自动降级为静态地图图片（`/api/staticmap`）；
- 配好 `AMAP_JS_KEY` 后左栏是真正的交互地图。JS API 2.0 的 `securityJsCode` 不能放在前端，本项目内置了 `/_AMapService/` 反向代理（见 `app/routes.py` 的 `amap_proxy`），把 `AMAP_SECURITY_CODE` 填进 `.env` 即可，本地开发不需要 Nginx；
- 前端把 `serviceHost` 设为 `${location.origin}/_AMapService`，这个值必须是「源 + 前缀」的完整地址，只写主机名会让 JS API 把主机名拼进路径。

页面自检（需要 Chrome）：

```powershell
chrome --headless=new --disable-gpu --remote-debugging-port=9223 --remote-allow-origins=* `
  --user-data-dir=.chrome-tmp http://127.0.0.1:8000
python scripts/cdp_check.py
```

输出里 `container=false` 说明地图没起来（多半是 key 平台不是「Web端 (JS API)」）。

## 测试

```powershell
pytest -v
```

全部用例都 mock 外部调用，不会消耗高德额度（46 项）。

真实链路冒烟（会消耗额度，手工执行）：

```powershell
uvicorn app.main:app --port 8123
python scripts/smoke.py http://127.0.0.1:8123
```

## Ubuntu 部署

```bash
conda env create -f environment.yml
sudo useradd -r -s /bin/false dailyfood
sudo mkdir -p /opt/daily-food && sudo chown dailyfood /opt/daily-food
# 拷贝代码与 .env 到 /opt/daily-food
sudo cp deploy/daily-food.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now daily-food
```

`deploy/daily-food.service` 里的 `ExecStart` 指向 `.venv/bin/uvicorn`；如果用 conda 环境，改成
`ExecStart=/opt/conda/envs/daily-food/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`。

Nginx 配置见 `deploy/nginx.conf.example`，把 `REPLACE_WITH_SECURITY_CODE` 换成 JS API 安全密钥。

**已上线实例**（2026-11-07）：**https://www.whyx.site**（Caddy 自动 HTTPS，HTTP 自动 308 跳转）
- Ubuntu 22.04 / systemd 托管 uvicorn，端口 9000，随开机自启；
- Caddy 站点 `www.whyx.site` 反代到 9000，Let's Encrypt 自动签发证书；`http://www.whyx.site` 自动跳 HTTPS；
- 原 xray（443 代理）已按用户要求停止并释放 443；rss/search 两个子域名站点未受影响；
- 代码在 `/opt/daily-food`，`daily-food.db` 含名人堂数据；
- 重新部署：本地改代码后跑 `python scripts/upload_to_vps.py` 上传，再 `python scripts/run_deploy.py` 重启（SSH 信息用环境变量 `DSH_SSH_HOST/PORT/USER/PASSWORD` 提供）。

## 额度与降级

- 周边池按「日期 + 网格（约 500m）+ 半径」缓存，跨日失效；同一区域的人共用一次外部调用；
- 搜索缓存 5 分钟；每 IP 20 次/分钟；
- 每日外部调用上限 `DAILY_CALL_LIMIT`（默认 500），到 80% 打 WARN，到上限后只读缓存；
- 降级顺序：当日池 → 陈旧池（`meta.stale=true`）→ 空态；接口不返回 5xx。

## 目录

```
app/     FastAPI 后端（config/models/geo/picker/store/amap/guard/routes/main）
web/     静态前端（index.html / app.js / style.css）
tests/   pytest（全部 mock）
scripts/ 真实链路冒烟脚本
deploy/  systemd 与 Nginx 示例
```
