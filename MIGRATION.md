# 换机器 / 换 Harness 操作说明

> 目标：在新机器上从零跑起这个仓库（美食雷达 + 吃饭推荐网站），并且让定时任务也跑起来。
> 全程不需要读旧机器的任何文件，只读本文件即可。

---

## 一、准备

### 1. 装 Python
- 版本 ≥ 3.10
- Windows 建议用 conda / 官方安装包；Linux 用系统 python3 或 pyenv

### 2. 拉代码
```bash
git clone https://github.com/whyx007/daily-food.git
cd daily-food
```

> 仓库里**没有**数据库（`*.db` 被 `.gitignore` 排除），也没有 `.env`。
> 数据靠 `radar/seeds/*.json`（作者 + 线索原文）重建，配置靠你自己新建 `.env`。

### 3. 装依赖
```bash
pip install -r requirements.txt
```
雷达只用到 `httpx`；网站另需 `fastapi / uvicorn / pydantic / pydantic-settings`——`requirements.txt` 里都有。

---

## 二、配 `.env`（必须，否则核验环节跳过）

在**仓库根目录**新建 `.env`（可以从 `.env.example` 复制）：

```ini
AMAP_KEY=你的高德Web服务Key
```

要点：
- Key 类型必须是高德控制台的 **「Web 服务」**（不是「Web端(JS API)」），否则核验会报 `USERKEY_PLAT_NOMATCH`；
- 没有 Key 也能跑，`verify` 会自动跳过，表单照样出，只是少了「已核验」那 10 分；
- `.env` 不要提交（已在 `.gitignore` 里）。

---

## 三、跑美食雷达

```bash
python -m radar.cli all        # = seed + verify + build + report
```

只跑其中某步也行：

| 命令 | 作用 |
|---|---|
| `python -m radar.cli seed` | 导入 `radar/seeds/*.json`（作者 + 线索） |
| `python -m radar.cli verify` | 高德核验每家店（逐条限速，几十秒） |
| `python -m radar.cli build` | 打分 + 聚合 + 导出 |
| `python -m radar.cli report` | 命令行打印结果 |

**产物**（`radar/out/` 下）：
- `food_table.md` —— 按十个品类分组的表单
- `food_table.csv` —— Excel 直接打开
- `index.html` —— 网页版，顶部可按品类筛选

**期望结果**（截至 2026-11-09 的基线）：
```
约 200+ 家；十个品类：牛羊肉小炒 / 汉民泡馍 / 水盆羊肉 / 饺子蒸饺 / 肉夹馍 /
凉皮酿皮 / 米线 / 面 / 烤肉 / 炒菜
区域标记：高新区 / 长安区 / 鄠邑区（其余为 -）
```
数量不必逐位对齐——你补的新线索会让它变多。

---

## 四、让定时任务跑起来

**关键：定时任务本身不在 git 里。**

DSH 的定时任务是 Harness 侧的持久化对象（`schedule_create` 建的），绑在某个 session id 上。
换机器 / 换 Harness 必须**重建一次**。参数见 `radar/SCHEDULE.md`，简版：

```
schedule_create(
  title  = "刷新西安美食雷达",
  rrule  = "DTSTART;TZID=Asia/Shanghai:20261110T083000\nRRULE:FREQ=DAILY",
  target = "this_session",
  prompt = <把 radar/SCHEDULE.md 里那段 prompt 粘过来，把 <REPO> 换成本机仓库路径>
)
```

时间可自己改（`T083000` = 早上 8:30），`TZID` 表示按北京时间的钟点走。

---

## 五、跑吃饭推荐网站（可选）

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8123
# 浏览器打开 http://127.0.0.1:8123
```

局域网给手机看（同一 WiFi）：
```powershell
pwsh -File scripts\serve_lan.ps1        # 绑 0.0.0.0，会打印本机局域网地址
```

注意：
- 网站的数据在 `daily-food.db`（首次启动自动建库，并用 `data/classics.json` 灌名人堂种子）；
- 网站和雷达是**两套独立数据**，互不影响（雷达用自己的 `radar/radar.db`）。

---

## 六、换机器后自查清单

按顺序打勾，任一不过就查下一节：

- [ ] `git log --oneline -3` 能看到最新提交
- [ ] `python -m radar.cli report` 不报 `ModuleNotFoundError`
- [ ] `python -m radar.cli all` 跑完，`radar/out/food_table.md` 里有多家店
- [ ] `radar/out/index.html` 用浏览器打开，顶部品类筛选能点
- [ ] 定时任务在 `schedule_list` 里是 `active`，`scheduledAtLocal` 是你要的钟点

---

## 七、常见问题

**`ModuleNotFoundError: No module named 'radar'`**
→ 必须在**仓库根目录**执行（`radar/` 是顶层包）。别在 `radar/` 目录里面跑。

**`ModuleNotFoundError: httpx`**
→ `pip install -r requirements.txt`，或确认用的是想用的那个 Python（`python -c "import sys; print(sys.executable)"`）。

**核验全失败 / 报 `USERKEY_PLAT_NOMATCH`**
→ `.env` 里的 Key 不是「Web 服务」类型。

**核验大量报 `CUQPS_HAS_EXCEEDED_THE_LIMIT`**
→ 高德个人 Key 并发受限。代码已内置限速（每条 0.35 s）和限流重试；仍超限就等几分钟重跑 `verify`，已核验的会跳过。

**`git push` 报 `Failed to connect to github.com:443` / `Connection was reset`**
→ 这类网络是**间歇性**的。用「探端口 + 重试」：
```powershell
$env:GIT_TERMINAL_PROMPT="0"
for ($i=1; $i -le 8; $i++) {
  $r = Test-NetConnection -ComputerName github.com -Port 443 -WarningAction SilentlyContinue
  if (-not $r.TcpTestSucceeded) { Write-Host "attempt $i blocked"; Start-Sleep 6; continue }
  git push origin main
  if ($LASTEXITCODE -eq 0) { Write-Host "OK"; break }
  Start-Sleep 6
}
```
不要加 `-c http.version=HTTP/1.1`（某些网络下反而被重置）。

**想确认远端到底有没有推上去**
→ 看 `git rev-parse HEAD` 和 `git rev-parse origin/main` 是否相同；相同时 push 会提示 `Everything up-to-date`。

**两台机器各跑一份，怎么合并数据**
→ 各自 `git add radar/seeds radar/out && git commit`，推送前用 `python -m radar.merge <json>` 的去重逻辑比对，
   或手工对齐 `seeds/claims.json`（key 是 `(poi_name, author_id, url)`，重复会被自动跳过）。

---

## 八、目录速览

```
app/ web/           吃饭推荐网站（FastAPI + 前端）
radar/              美食雷达（独立模块，自带 SQLite）
  seeds/            作者与线索（入库，是数据的真源）
  out/              导出的表单（入库，方便直接看）
  agent_task.md     定时任务每天要做的步骤（可移植）
  SCHEDULE.md       定时任务的重建参数
deploy/ scripts/    部署与运维脚本
requirements.txt    依赖
```
