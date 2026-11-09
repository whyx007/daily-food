"""把采集回来的 JSON（{"authors":[...],"claims":[...]}）合并进 seeds/。

用法：python -m radar.merge <file.json> [--dry]

去重规则：authors 按 id，claims 按 (poi_name, author_id, url)。
"""
import json
import sys
from pathlib import Path

SEEDS = Path(__file__).resolve().parent / "seeds"


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def merge(payload: dict, dry: bool = False) -> dict:
    authors_path = SEEDS / "authors_extra.json"
    claims_path = SEEDS / "claims.json"
    authors = _load(authors_path, [])
    claims = _load(claims_path, [])

    have_authors = {a["id"] for a in _load(SEEDS / "authors.json", [])} | {a["id"] for a in authors}
    have_claims = {(c["poi_name"], c["author_id"], c.get("url", "")) for c in claims}

    new_authors, new_claims = [], []
    for a in payload.get("authors", []):
        if a["id"] in have_authors:
            # 已存在就更新 note/trust（不改 id）
            for existing in authors:
                if existing["id"] == a["id"]:
                    existing.update({k: v for k, v in a.items() if k != "id"})
            continue
        new_authors.append(a)
        have_authors.add(a["id"])

    for c in payload.get("claims", []):
        key = (c["poi_name"], c["author_id"], c.get("url", ""))
        if key in have_claims:
            continue
        if c["author_id"] not in have_authors:
            print(f"跳过（未知作者 {c['author_id']}）：{c['poi_name']}")
            continue
        new_claims.append(c)
        have_claims.add(key)

    if dry:
        return {"authors": len(new_authors), "claims": len(new_claims), "dry": True}

    authors.extend(new_authors)
    claims.extend(new_claims)
    authors_path.write_text(json.dumps(authors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    claims_path.write_text(json.dumps(claims, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"authors": len(new_authors), "claims": len(new_claims)}


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    path = Path(argv[0])
    payload = json.loads(path.read_text(encoding="utf-8"))
    dry = "--dry" in argv
    result = merge(payload, dry=dry)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
