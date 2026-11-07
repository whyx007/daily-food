"""把数据库里的经典馆子导出成可提交的种子文件。

用法：python scripts/export_classics.py [输出路径]
默认输出 data/classics.json，启动时若数据库为空会自动导入它。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.store import Store  # noqa: E402

FIELDS = ("poiid", "name", "lat", "lng", "rating", "cost", "type", "address", "note")


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "classics.json"
    db = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "daily-food.db"
    if not db.exists():
        print(f"db not found: {db}")
        return 1
    store = Store(str(db))
    items = [{k: row.get(k) for k in FIELDS} for row in store.list_classics()]
    store.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"version": 1, "items": items},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"exported {len(items)} classics -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
