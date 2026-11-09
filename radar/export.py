"""导出最终美食表单：Markdown / CSV / 可筛选 HTML。"""
import csv
import html
import json
from pathlib import Path

from radar import db

OUT = Path(__file__).resolve().parent / "out"


def _rows(conn):
    return conn.execute("""
        SELECT poiid,name,address,category,trust,consensus,endorsement,
               source_count,mention_count,reason,authors_json,first_seen,last_seen,rating,cost
        FROM pois ORDER BY trust DESC, mention_count DESC
    """).fetchall()


def _cat(row) -> str:
    return (row["category"] or "").replace("餐饮服务;", "").split(";")[0] or "其他"


def export(conn) -> dict:
    OUT.mkdir(exist_ok=True)
    rows = _rows(conn)
    cats = sorted({_cat(r) for r in rows})

    # CSV
    csv_path = OUT / "food_table.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["店名", "品类", "地址", "综合可信度", "重合度", "博主力荐", "独立来源数", "提及次数",
                    "推荐理由", "来源", "首次提及", "最近提及", "poiid"])
        for r in rows:
            w.writerow([r["name"], _cat(r), r["address"] or "", r["trust"], r["consensus"],
                        r["endorsement"], r["source_count"], r["mention_count"], r["reason"] or "",
                        "/".join(json.loads(r["authors_json"] or "[]")),
                        (r["first_seen"] or "")[:10], (r["last_seen"] or "")[:10], r["poiid"]])

    # Markdown
    md = ["# 西安美食雷达 · 表单", ""]
    md.append(f"共 **{len(rows)}** 家（已通过高德核验）。综合可信度 = 0.6×重合度 + 0.4×博主力荐 + 核验加成。")
    md.append("")
    md.append("| # | 店名 | 品类 | 综合 | 重合度 | 博主力荐 | 来源数 | 推荐理由 | 来源 |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        reason = (r["reason"] or "").replace("|", "／").replace("\n", " ")[:60]
        md.append(f"| {i} | {r['name']} | {_cat(r)} | **{r['trust']}** | {r['consensus']} | "
                  f"{r['endorsement']} | {r['source_count']} | {reason} | "
                  f"{'、'.join(json.loads(r['authors_json'] or '[]'))} |")
    (OUT / "food_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # HTML（可按品类筛选）
    cards = []
    for r in rows:
        authors = "、".join(json.loads(r["authors_json"] or "[]"))
        color = "#1a7f37" if r["trust"] >= 70 else ("#9a6700" if r["trust"] >= 45 else "#8b949e")
        cards.append(f"""
        <div class="card" data-cat="{html.escape(_cat(r))}">
          <div class="head"><span class="name">{html.escape(r['name'])}</span>
            <span class="trust" style="color:{color}">{r['trust']}</span></div>
          <div class="meta">{html.escape(_cat(r))} · {html.escape(r['address'] or '地址未知')}</div>
          <div class="dims">
            <span>重合度 <b>{r['consensus']}</b></span>
            <span>博主力荐 <b>{r['endorsement']}</b></span>
            <span>来源 <b>{r['source_count']}</b></span>
          </div>
          <div class="reason">“{html.escape((r['reason'] or '')[:120])}”</div>
          <div class="src">{html.escape(authors)} · 提及 {r['mention_count']} 次</div>
        </div>""")

    chips = "".join(f'<button class="chip" data-cat="{html.escape(c)}">{html.escape(c)}</button>'
                    for c in cats)
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>西安美食雷达</title><style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f7f9;color:#1f2328}}
header{{padding:18px 24px;background:#fff;border-bottom:1px solid #e5e7eb}}
h1{{margin:0;font-size:20px}} .sub{{color:#57606a;font-size:13px;margin-top:4px}}
#chips{{display:flex;gap:8px;flex-wrap:wrap;padding:12px 24px;background:#fff;border-bottom:1px solid #e5e7eb}}
.chip{{padding:5px 12px;border:1px solid #d0d7de;border-radius:999px;background:#fff;cursor:pointer;font-size:13px}}
.chip.active{{background:#1f2328;color:#fff}}
#grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;padding:16px 24px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px}}
.head{{display:flex;justify-content:space-between;align-items:baseline}}
.name{{font-size:16px;font-weight:600}} .trust{{font-weight:700;font-size:15px}}
.meta{{color:#57606a;font-size:12px;margin-top:4px}}
.dims{{display:flex;gap:12px;margin-top:8px;font-size:12px;color:#57606a}}
.dims b{{color:#1f2328}}
.reason{{margin-top:8px;font-size:13px;line-height:1.6;color:#24292f}}
.src{{margin-top:8px;font-size:11px;color:#8b949e}}
</style></head><body>
<header><h1>🍜 西安美食雷达</h1>
<div class="sub">可信度 = 来源先验 + 反软广信号 + 交叉来源 + 高德核验 · 共 {len(rows)} 家 · 更新 {db.now()[:16]}</div></header>
<div id="chips"><button class="chip active" data-cat="__all">全部</button>{chips}</div>
<div id="grid">{''.join(cards)}</div>
<script>
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('active'));
  c.classList.add('active');
  const cat=c.dataset.cat;
  document.querySelectorAll('.card').forEach(el=>{{
    el.style.display=(cat==='__all'||el.dataset.cat===cat)?'':'none';
  }});
}});
</script></body></html>"""
    (OUT / "index.html").write_text(page, encoding="utf-8")

    return {"pois": len(rows), "categories": cats,
            "md": str(OUT / "food_table.md"), "csv": str(csv_path),
            "html": str(OUT / "index.html")}
