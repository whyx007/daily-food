# 今天吃啥（daily-food）

每天随机推荐一家附近餐厅：左侧高德地图 + 导航，右侧搜索、候选列表、共享名人堂。
设计文档见 [docs/superpowers/specs/2026-11-07-daily-food-design.md](docs/superpowers/specs/2026-11-07-daily-food-design.md)，
实现计划见 [docs/superpowers/plans/2026-11-07-daily-food-plan.md](docs/superpowers/plans/2026-11-07-daily-food-plan.md)。

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
- 想用交互式地图，再申请「Web端 (JS API)」key 与安全密钥，填 `AMAP_JS_KEY` / `AMAP_SECURITY_CODE`，并在 Nginx 配置 `/_AMapService/` 反代。

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
