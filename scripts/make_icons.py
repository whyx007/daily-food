"""从用户提供的图标生成网站 favicon 与页头 logo。

用法：python scripts/make_icons.py <source.png>
输出：web/favicon.png (32x32)、web/icon-180.png (180x180)、web/logo.png (96x96)
"""
import sys
from pathlib import Path

from PIL import Image

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else None
WEB = Path(__file__).resolve().parent.parent / "web"


def main() -> int:
    if SRC is None or not SRC.exists():
        print("usage: python scripts/make_icons.py <source.png>")
        return 1
    img = Image.open(SRC)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    for name, size in (("favicon.png", 32), ("icon-180.png", 180), ("logo.png", 96)):
        out = img.resize((size, size), Image.LANCZOS)
        out.save(WEB / name, "PNG", optimize=True)
        print(f"wrote web/{name} {size}x{size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
