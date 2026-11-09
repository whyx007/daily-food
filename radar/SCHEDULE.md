# 定时任务规格（可在任意 DeepSeek Harness 里复刻）

## 重要：定时任务本身**不在 git 里**

DSH 的定时任务是 Harness 侧的持久化状态（`schedule_create` 建的对象），绑定在**某个 session id** 上，
不落进仓库。所以换一个 Harness / 换一台机器，**需要在新环境里重新创建一次**。

在 git 里的、真正可移植的是两样东西：
1. **执行手册** `radar/agent_task.md` —— 干什么、怎么干、红线；
2. **数据与代码** `radar/` 全目录 + `radar/seeds/*.json` —— 任何人 clone 后跑 `python -m radar.cli all`
   就能重建出同样的表单。

## 在新 Harness 里创建任务

先 clone 仓库、确认 `python -m radar.cli report` 能跑（见 `agent_task.md` 第 0 节），
然后在新会话里用同样参数建任务：

```
schedule_create(
  title  = "刷新西安美食雷达",
  rrule  = "DTSTART;TZID=Asia/Shanghai:20261110T083000\nRRULE:FREQ=DAILY",
  target = "this_session"
)
```

`prompt` 用下面这段（**把 `<REPO>` 换成本机仓库路径**，其余保持原样）：

```
按 <REPO>/radar/agent_task.md 执行当天的美食雷达刷新：

1) 读 radar/agent_task.md 与 radar/seeds/claims.json，确认已有店名与规则；
2) 用 web_search 找尚未覆盖品类的西安本地美食文章
   （只采信 sina/k.sina/sohu/163/thepaper/wingontravel/you.ctrip.com/post.smzdm.com；
     跳过小红书、抖音、公众号、知乎、百度百科、toutiao）；
3) 用 web_fetch 打开页面，摘原文里真实存在的句子做 snippet，
   追加 3–8 条线索到 radar/seeds/claims.json（不编造、不重复）；
4) 在 <REPO> 下运行：python -m radar.cli seed / verify / build / report
   （解释器按 agent_task.md 第 0 节自行确定）；
5) 回报：新增几家、核验通过几家、哪几家高德查无此店、表单前 5 名的变化。

红线：只改 radar/ 目录，不碰 app/、web/、daily-food.db；遇到 403/412/验证码直接跳过。
```

## 注意

- **Python 路径不要跨机照抄**：原机器用的是 `D:\Miniconda3\envs\daily-food\python.exe`，
  新机器请按 `agent_task.md` 第 0 节自行确定。
- **`AMAP_KEY` 需各自配置**：在仓库根 `.env` 写 `AMAP_KEY=...`（高德「Web 服务」类型 Key）。
  没有 Key 就跳过 `verify`，`build` 仍可出表。
- **数据库不入库**：`radar/radar.db` 被 `.gitignore` 的 `*.db` 排除，靠 `seeds/*.json` 重建。
- 若希望两台机器共享同一份表单，建议各自跑完后 `git add radar/out radar/seeds && git commit`，
  以 git 作为同步媒介（注意 seeds 合并时可能有重复，用 `python -m radar.merge` 的去重逻辑处理）。
