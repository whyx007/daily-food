"""导出最终美食表单：按 9 个品类分组，Markdown / CSV / 可筛选 HTML。"""
import csv
import html
import json
from pathlib import Path

from radar import db
from radar.categories import CANONICAL

OUT = Path(__file__).resolve().parent / "out"

_COLS = ("poiid,name,address,category,trust,consensus,endorsement,"
         "source_count,mention_count,reason,authors_json,first_seen,last_seen")


def _rows(conn):
    return conn.execute(
        f"SELECT {_COLS} FROM pois ORDER BY trust DESC, mention_count DESC"
    ).fetchall()


def _grouped(rows):
    """按九大品类分组；返回 (有序组, 未归类)。"""
    groups = {c: [] for c in CANONICAL}
    other = []
    for r in rows:
        cat = r["category"] or ""
        if cat in groups:
            groups[cat].append(r)
        else:
            other.append(r)
    return groups, other


def _reason(r, n=64):
    return (r["reason"] or "").replace("|", "／").replace("\n", " ")[:n]


def _authors(r):
    return "、".join(json.loads(r["authors_json"] or "[]"))


def export(conn) -> dict:
    OUT.mkdir(exist_ok=True)
    rows = _rows(conn)
    groups, other = _grouped(rows)

    # ---------- CSV ----------
    csv_path = OUT / "food_table.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["品类", "店名", "地址", "综合", "重合度", "博主力荐", "来源数",
                    "提及次数", "推荐理由", "来源", "最近提及", "poiid"])
        for cat in CANONICAL:
            for r in groups[cat]:
                w.writerow([cat, r["name"], r["address"] or "", r["trust"], r["consensus"],
                            r["endorsement"], r["source_count"], r["mention_count"],
                            r["reason"] or "", _authors(r),
                            (r["last_seen"] or "")[:10], r["poiid"]])
        for r in other:
            w.writerow(["未归类", r["name"], r["address"] or "", r["trust"], r["consensus"],
                        r["endorsement"], r["source_count"], r["mention_count"],
                        r["reason"] or "", _authors(r), (r["last_seen"] or "")[:10], r["poiid"]])

    # ---------- Markdown ----------
    md = ["# 西安美食雷达 · 表单", ""]
    md.append("综合可信度 = 0.6×重合度 + 0.4×博主力荐 + 10（高德核验加成）。")
    md.append("")
    md.append("| 品类 | 家数 |")
    md.append("|---|---|")
    for cat in CANONICAL:
        md.append(f"| {cat} | {len(groups[cat])} |")
    md.append(f"| **合计** | **{len(rows)}** |")
    md.append("")

    for cat in CANONICAL:
        items = groups[cat]
        md.append(f"## {cat}（{len(items)} 家）")
        md.append("")
        if not items:
            md.append("_待补充_")
            md.append("")
            continue
        md.append("| # | 店名 | 综合 | 重合度 | 博主力荐 | 来源数 | 推荐理由 | 来源 |")
        md.append("|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(items, 1):
            md.append(f"| {i} | {r['name']} | **{r['trust']}** | {r['consensus']} | "
                      f"{r['endorsement']} | {r['source_count']} | {_reason(r)} | {_authors(r)} |")
        md.append("")

    if other:
        md.append("## 未归类（暂不进九大品类）")
        md.append("")
        md.append("| 店名 | 综合 | 来源 |")
        md.append("|---|---|---|")
        for r in other:
            md.append(f"| {r['name']} | {r['trust']} | {_authors(r)} |")
        md.append("")

    (OUT / "food_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # ---------- HTML ----------
    def card(r):
        color = "#1a7f37" if r["trust"] >= 70 else ("#9a6700" if r["trust"] >= 45 else "#8b949e")
        return f"""
      <div class="card" data-cat="{html.escape(r['category'] or '未归类')}">
        <div class="head"><span class="name">{html.escape(r['name'])}</span>
          <span class="trust" style="color:{color}">{r['trust']}</span></div>
        <div class="meta">{html.escape(r['address'] or '地址未知')}</div>
        <div class="dims"><span>重合度 <b>{r['consensus']}</b></span>
          <span>博主力荐 <b>{r['endorsement']}</b></span>
          <span>来源 <b>{r['source_count']}</b></span></div>
        <div class="reason">“{html.escape((r['reason'] or '')[:110])}”</div>
        <div class="src">{html.escape(_authors(r))} · 提及 {r['mention_count']} 次</div>
      </div>"""

    sections = []
    for cat in CANONICAL:
        items = groups[cat]
        body = "".join(card(r) for r in items) or '<div class="empty">待补充</div>'
        sections.append(f'<section data-cat="{html.escape(cat)}">'
                        f'<h2>{html.escape(cat)} <span class="count">{len(items)}</span></h2>'
                        f'<div class="grid">{body}</div></section>')
    if other:
        sections.append('<section data-cat="未归类"><h2>未归类 <span class="count">'
                        f'{len(other)}</span></h2><div class="grid">'
                        + "".join(card(r) for r in other) + "</div></section>")

    chips = "".join(
        f'<button class="chip" data-cat="{html.escape(c)}">{html.escape(c)} '
        f'<span class="n">{len(groups[c])}</span></button>' for c in CANONICAL
    )
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>西安美食雷达</title><style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f6f7f9;color:#1f2328}}
header{{padding:18px 24px;background:#fff;border-bottom:1px solid #e5e7eb}}
h1{{margin:0;font-size:20px}} .sub{{color:#57606a;font-size:13px;margin-top:4px}}
#chips{{display:flex;gap:8px;flex-wrap:wrap;padding:12px 24px;background:#fff;border-bottom:1px solid #e5e7eb;position:sticky;top:0;z-index:5}}
.chip{{padding:5px 12px;border:1px solid #d0d7de;border-radius:999px;background:#fff;cursor:pointer;font-size:13px}}
.chip.active{{background:#1f2328;color:#fff}} .n{{color:#8b949e;font-size:11px}} .chip.active .n{{color:#c9d1d9}}
section{{padding:8px 24px 4px}} h2{{font-size:16px;margin:14px 0 10px}} .count{{color:#8b949e;font-size:12px;font-weight:400}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px}}
.head{{display:flex;justify-content:space-between;align-items:baseline}}
.name{{font-size:16px;font-weight:600}} .trust{{font-weight:700;font-size:15px}}
.meta{{color:#57606a;font-size:12px;margin-top:4px}}
.dims{{display:flex;gap:12px;margin-top:8px;font-size:12px;color:#57606a}} .dims b{{color:#1f2328}}
.reason{{margin-top:8px;font-size:13px;line-height:1.6;color:#24292f}}
.src{{margin-top:8px;font-size:11px;color:#8b949e}}
.empty{{color:#8b949e;font-size:13px;padding:8px 0}}
</style></head><body>
<header><h1>🍜 西安美食雷达</h1>
<div class="sub">共 {len(rows)} 家 · 双维度：重合度（多源交叉）+ 博主力荐 · 更新 {db.now()[:16]}</div></header>
<div id="chips"><button class="chip active" data-cat="__all">全部 <span class="n">{len(rows)}</span></button>{chips}</div>
{''.join(sections)}
<script>
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('active'));
  c.classList.add('active');
  const cat=c.dataset.cat;
  document.querySelectorAll('section').forEach(s=>{{
    s.style.display=(cat==='__all'||s.dataset.cat===cat)?'':'none';
  }});
}});
</script></body></html>"""
    (OUT / "index.html").write_text(page, encoding="utf-8")

    counts = {c: len(groups[c]) for c in CANONICAL}
    return {"pois": len(rows), "counts": counts, "other": len(other),
            "md": str(OUT / "food_table.md"), "csv": str(csv_path),
            "html": str(OUT / "index.html")}
