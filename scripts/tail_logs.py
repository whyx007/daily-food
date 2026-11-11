"""命令行查看访问日志。

用法：
    python scripts/tail_logs.py                 # 最近 20 条
    python scripts/tail_logs.py 100             # 最近 100 条
    python scripts/tail_logs.py --path /api     # 只看某前缀
    python scripts/tail_logs.py --status 500    # 只看 5xx（也有 4xx）
    python scripts/tail_logs.py --stats         # 按路径/IP 汇总
"""
import sys
from collections import Counter

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app import accesslog  # noqa: E402


def main(argv):
    n = 20
    path = ""
    status = ""
    stats = "--stats" in argv
    rest = [a for a in argv if not a.startswith("--")]
    if rest:
        n = int(rest[0])
    for i, a in enumerate(argv):
        if a == "--path" and i + 1 < len(argv):
            path = argv[i + 1]
        if a == "--status" and i + 1 < len(argv):
            status = argv[i + 1]

    if stats:
        items = accesslog.tail(2000, files=5)
        print(f"最近 {len(items)} 条记录的汇总：\n")
        print("路径 Top 10：")
        for p, c in Counter(i.get("path", "") for i in items).most_common(10):
            print(f"  {c:>5}  {p}")
        print("\nIP Top 10：")
        for p, c in Counter(i.get("ip", "") for i in items).most_common(10):
            print(f"  {c:>5}  {p}")
        print("\n状态码：")
        for p, c in Counter(str(i.get("status", "")) for i in items).most_common():
            print(f"  {c:>5}  {p}")
        return 0

    items = accesslog.tail(n, path_prefix=path, status=status)
    print(f"{'时间':<20}{'IP':<16}{'方法':<6}{'状态':<6}{'耗时':<8}路径")
    print("-" * 96)
    for e in items:
        q = f"?{e['query']}" if e.get("query") else ""
        print(f"{e.get('t',''):<20}{e.get('ip',''):<16}{e.get('method',''):<6}"
              f"{str(e.get('status','')):<6}{str(e.get('ms','')) + 'ms':<8}{e.get('path','')}{q}")
    print(f"\n共 {len(items)} 条 · 文件 {accesslog.LOG_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
