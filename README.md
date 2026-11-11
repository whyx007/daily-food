# 今天吃啥（daily-food）

每天随机推荐一家附近餐厅：左侧高德地图 + 导航，右侧搜索、候选列表、共享名人堂。

交互要点：

- 三个模式按钮（区域随机 / 经典馆子 / 高分优先）有选中态与按压反馈；
- 点「高分优先」会弹出评分档位菜单（不限 / 4.5+ / 4+ / 3.5+），选中档位后按钮上会显示当前过滤值；
- **距离档位**（3km / 5km / 15km）严格生效：切换后当前视图按新半径重新拉取；经典馆子模式下距离档位置灰；
- **设置（⚙ 地图右上角）**：列表排序可切换「按距离排序 / 按打分排序」；
- **右侧信息栏可折叠**：面板左侧边缘的 «/» 按钮可收起/展开，收起后地图占满；
- **经典馆子开关**：距离栏右侧的「显示经典馆子」checkbox **默认勾选**，控制**地图上**是否显示经典馆子的位置——勾选后每家经典馆子显示一个上下闪动的 ⭐（点击可选中、右键可加菜单），**新增/删除经典馆子时星星即时增删**；「⭐ 经典馆子」按钮仍是模式切换（列表列出全部经典馆子并可密码删除）；
- **点击地图任意位置** → 弹出商家信息卡：名称、类型、地址、评分、人均、电话、坐标，并可直接「去这里 / 加入经典馆子 / 设为出发点」；点位没有对应商家档案时会让你确认店名后按坐标录入；
- **快捷词片**：饺子 / 面 / 火锅 / 快餐 / 牛羊肉泡馍 / 葫芦头 / 炒菜 / 烧烤 +「✕ 取消」。普通模式下词片做**周边搜索（受 3km/5km/15km 距离档位约束）**；经典馆子模式下词片只在经典馆子里按名称过滤；「取消」清除筛选恢复默认列表；搜索框仍是全城搜索；
- **地图顶部搜索框** → 输入商家关键词（饺子、星巴克、火锅…）**按当前城市全城搜索**（不受距离档位约束，结果按离出发点的距离排序），**第一个结果自动成为首栏推荐店家**（地图标记、卡片、列表高亮同步），不用再点一次；
- **右键地图** → 就地弹出菜单：设为出发点（蓝点标记，距离与导航起点随之改变），或加入经典馆子——右键落在店铺标记上会直接带出店名，落在空白处会先逆地理编码识别该处最近的餐厅并预填店名（可编辑后再确认）；
- **出发点**显示在右侧栏顶部，用逆地理编码换成人能读的地名（优先小区/园区/商圈，其次「XX附近」，最后街道+路名），坐标与来源作副标题；点「用我的定位」可重置为当前位置。地名缓存 30 天，不额外消耗额度；
- **电话**：高德有收录的商家会在卡片里显示 📞 号码（可点击拨号），列表项也会带电话小图标；约四成商家有号码，没有的不显示；
- **点击列表项** → 首栏卡片切换成该店（地址、坐标、电话与三个按钮）；
- **地图默认不铺标记**：只有右侧列表选中某家时，才在地图上落一个标记并把视野移过去；
- **位置校正**：选中某家后，右键地图上它真正的位置，选「📌 把「店名」的位置校正到这里」，之后列表距离、地图标记、导航都用校正后的坐标（存 `poi_fixes` 表；撤销可 `DELETE /api/fixes/{poiid}`）；
- **右键右侧列表项** → 直接加入经典馆子；加入成功后右侧列表会立即切到「经典馆子」并高亮新增的那家，不用手动刷新；
- **经典馆子列表删除**：每项带 🗑 删除按钮，需输入删除密码（`.env` 的 `ADMIN_TOKEN`，本机与线上统一为 `XKKG`）确认后才删除；
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

**局域网访问**（同一 WiFi 下的手机/平板）：

```powershell
pwsh -File scripts\serve_lan.ps1            # 默认 8123 端口，绑 0.0.0.0
pwsh -File scripts\serve_lan.ps1 -Port 9000 # 换端口
```

脚本会把本机所有网卡 IP 的访问地址打印出来（形如 `http://192.168.1.7:8123`）。注意：

- 必须绑 `0.0.0.0`（绑 `127.0.0.1` 时局域网连不上）；
- Windows 防火墙需要放行 python 的入站连接（首次启动时弹窗选「允许」，当前 `daily-food` 的解释器规则已存在且覆盖「公用网络」）；
- 手机浏览器访问 `http://` 地址时**不提供定位权限**（非 HTTPS 不是安全上下文），会退回 `.env` 里的 `DEFAULT_LAT/DEFAULT_LNG`；想用当前位置就右键地图「设为出发点」。默认点已设为**西安高新区**（`34.172176, 108.862074`），无定位环境下打开即为西安附近。

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

## Docker 部署（当前线上方式）

镜像由仓库里的 `Dockerfile` + `docker-compose.yml` 构建，容器内监听 8000，宿主机映射到 **9000**：

```bash
cd /opt/daily-food
sudo docker compose build
sudo docker compose up -d
```

- 配置走 `env_file: .env`（不进镜像），数据库通过 `DB_PATH=/data/daily-food.db` 落到宿主机 `./data-store/`，重启/重建镜像都保留名人堂数据；
- `restart: unless-stopped`，宿主重启后容器自动拉起；
- `.env` 的 `RADIUS_OPTIONS` 需要包含新档位（当前 `3000,5000,15000`）。

**代码同步**：本地提交后用 git bundle 走 SSH 推送（GitHub 不可达时也能用），一条命令完成同步 + 停旧服务 + 迁移数据库 + 重建容器 + 健康检查：

```powershell
python scripts/deploy_docker.py        # 完整部署
python scripts/deploy_docker.py --dry  # 只看远端现状
```

脚本做的事：`git bundle create` → SFTP 上传 → 停并 disable 旧的 systemd 服务 → 把 `daily-food.db*` 复制进 `data-store/` → 远端 `git fetch <bundle> main && git reset --hard` → 修 `.env` 半径档位 → `docker compose build`/`up -d` → 轮询 `/api/health`。

## Ubuntu 裸机部署（已被 Docker 取代，保留备查）

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

**已上线实例**（2026-11-07，2026-11-09 改为 Docker）：**https://www.whyx.site**（Caddy 自动 HTTPS，HTTP 自动 308 跳转）
- Ubuntu 22.04 / **Docker 容器 `daily-food`**，宿主 9000 → 容器 8000，`restart: unless-stopped` 随开机自启；
- 旧的 systemd 单元 `daily-food.service` 已 `stop` + `disable`，代码仍在 `/opt/daily-food`（同一个 git 仓库，供 bundle 同步用）；
- Caddy 站点 `www.whyx.site` 反代到 9000，Let's Encrypt 自动签发证书；`http://www.whyx.site` 自动跳 HTTPS；
- 原 xray（443 代理）已按用户要求停止并释放 443；rss/search 两个子域名站点未受影响；
- 数据：`/opt/daily-food/data-store/daily-food.db`（含 8 家名人堂），容器内 `/data`；
- 重新部署：`python scripts/deploy_docker.py`（SSH 信息用环境变量 `DSH_SSH_HOST/PORT/USER/PASSWORD` 提供）。

## 访问日志

每次请求都会记一条 JSON Lines 到 `logs/access.log`（单文件 5MB 自动滚动，保留 5 个历史文件）：

```json
{"t":"2026-11-11 18:49:06","ip":"1.2.3.4","method":"GET","path":"/api/radar","query":"lat=34.17&lng=108.86","status":200,"ms":7.8,"ua":"Mozilla/5.0 …","ref":""}
```

**查看方式（三种任选）**

1. **浏览器**：打开 `http://127.0.0.1:8123/admin.html`（线上 `https://www.whyx.site/admin.html`），输入管理密码（`ADMIN_TOKEN`）后可筛选路径/IP/状态码，可开 5 秒自动刷新，顶部显示热点路径与来源 IP；
2. **命令行**：
   ```powershell
   python scripts/tail_logs.py              # 最近 20 条
   python scripts/tail_logs.py 100          # 最近 100 条
   python scripts/tail_logs.py --path /api  # 只看某前缀
   python scripts/tail_logs.py --status 500 # 只看 5xx
   python scripts/tail_logs.py --stats      # 按路径/IP/状态码汇总
   ```
3. **看原始文件**：`logs/access.log`（Docker 部署时映射到宿主 `/opt/daily-food/logs`），可用 `tail -f` 或 `jq` 过滤。

**安全**：查询串里若出现 `token`、`password`、`key` 等参数名，值会被替换成 `<hidden>`，密码不会进日志；`/api/admin/logs` 本身需要密码。跑测试时（`PYTEST_CURRENT_TEST`）不写日志，避免用例污染真实记录。



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

## 额度与降级

高德免费额度按日计算，服务端有 DAILY_CALL_LIMIT（默认 500）熔断与 RATE_LIMIT_PER_MIN（默认 120）限流；
超出时会返回缓存结果并把 `meta.degraded` 置为 `daily_limit_reached` 或 `too_many_requests`。
