"""九个标准品类 + 归一化映射。

用户指定的分类：
  牛羊肉小炒（回民泡馍/小炒）、汉民泡馍（葫芦头/三鲜煮馍）、水盆羊肉、
  饺子蒸饺、肉夹馍、凉皮酿皮、米线、烤肉、炒菜
"""

CANONICAL = [
    "牛羊肉小炒",
    "汉民泡馍",
    "水盆羊肉",
    "饺子蒸饺",
    "肉夹馍",
    "凉皮酿皮",
    "米线",
    "烤肉",
    "炒菜",
]

# 关键词 -> 标准品类（按顺序匹配，先命中先得）
RULES = [
    ("葫芦头|梆梆肉|三鲜煮馍|煮馍|猪肠", "汉民泡馍"),
    ("水盆", "水盆羊肉"),
    ("烤肉|烤串|串串|烤面筋|烧烤|夜市", "烤肉"),
    ("凉皮|酿皮|擀面皮|米皮", "凉皮酿皮"),
    ("肉夹馍|腊汁肉|腊牛肉|白吉馍|潼关", "肉夹馍"),
    ("饺子|蒸饺|水饺|锅贴", "饺子蒸饺"),
    ("米线|米粉|螺蛳粉|过桥", "米线"),
    ("炒菜|陕菜|家常菜|盖浇饭|快餐|小炒肉", "炒菜"),
    ("泡馍|小炒|牛羊|羊肉泡|牛肉泡", "牛羊肉小炒"),
]


def normalize(category: str | None, sub: str | None = None) -> str | None:
    """把任意写法归到九个标准品类；无法归类返回 None。"""
    if category in CANONICAL:
        return category
    text = f"{category or ''} {sub or ''}"
    if not text.strip():
        return None
    for pattern, canon in RULES:
        if any(k in text for k in pattern.split("|")):
            return canon
    return None
