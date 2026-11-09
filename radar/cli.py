"""美食雷达 CLI。

用法：
    python -m radar.cli init      # 建库
    python -m radar.cli seed      # 导入 seeds/*.json（作者 + 线索）
    python -m radar.cli verify    # 高德核验未核验的线索
    python -m radar.cli build     # 打分 + 聚合 + 导出表单
    python -m radar.cli report    # 打印汇总
    python -m radar.cli all       # init+seed+verify+build+report
"""
import json
import sys
from pathlib import Path

import httpx

from radar import amap_verify, consolidate, db, export

SEEDS = Path(__file__).resolve().parent / "seeds"


def cmd_init(args):
    conn = db.init()
    print(f"库已初始化：{db.DB_PATH}")
    return conn


def cmd_seed(conn, args):
    authors = json.loads((SEEDS / "authors.json").read_text(encoding="utf-8"))
    extra = SEEDS / "authors_extra.json"
    if extra.exists():
        authors += json.loads(extra.read_text(encoding="utf-8"))
    for a in authors:
        a.setdefault("trust_final", a["trust_prior"])
        db.upsert_author(conn, a)
    conn.commit()
    print(f"作者 {len(authors)} 位")

    claims_path = SEEDS / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8")) if claims_path.exists() else []
    for c in claims:
        db.upsert_claim(conn, c)
    conn.commit()
    print(f"线索 {len(claims)} 条")


def cmd_verify(conn, args):
    key = amap_verify.load_key()
    if not key:
        print("缺少 AMAP_KEY，跳过核验")
        return
    limit = int(args[0]) if args else None
    with httpx.Client(timeout=20) as client:
        ok, bad = consolidate.verify_claims(conn, client, key, limit)
    print(f"核验成功 {ok} 条，失败 {bad} 条")


def cmd_build(conn, args):
    n_auth = consolidate.score_authors(conn)
    n_claim = consolidate.score_claims(conn)
    n_poi = consolidate.consolidate(conn)
    info = export.export(conn)
    print(f"打分：作者 {n_auth}，线索 {n_claim}，聚合店 {n_poi}")
    print(f"导出：{info['pois']} 家 -> {info['md']}")
    print("品类分布：" + "  ".join(f"{k}={v}" for k, v in info["counts"].items()))
    if info.get("other"):
        print(f"未归类：{info['other']} 家")
    print(f"HTML：{info['html']}")


def cmd_report(conn, args):
    rows = conn.execute("""SELECT name,category,trust,source_count,mention_count
                           FROM pois ORDER BY trust DESC""").fetchall()
    if not rows:
        print("暂无数据，先跑 build")
        return
    print(f"{'店名':<24}{'品类':<10}{'可信度':>6}{'来源':>5}")
    print("-" * 52)
    for r in rows:
        cat = (r["category"] or "").replace("餐饮服务;", "").split(";")[0][:8]
        print(f"{r['name'][:22]:<24}{cat:<10}{r['trust']:>6}{r['source_count']:>5}")
    unver = conn.execute("SELECT COUNT(*) c FROM claims WHERE verified=0").fetchone()["c"]
    print(f"\n未核验线索：{unver} 条")


def main(argv):
    conn = db.connect()
    conn.executescript((Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8"))
    conn.commit()
    cmd = argv[0] if argv else "report"
    args = argv[1:]
    if cmd == "init":
        cmd_init(args)
    elif cmd == "seed":
        cmd_seed(conn, args)
    elif cmd == "verify":
        cmd_verify(conn, args)
    elif cmd == "build":
        cmd_build(conn, args)
    elif cmd == "report":
        cmd_report(conn, args)
    elif cmd == "all":
        cmd_seed(conn, args)
        cmd_verify(conn, args)
        cmd_build(conn, args)
        cmd_report(conn, args)
    else:
        print(__doc__)
        return 1
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
