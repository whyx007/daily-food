"""访问日志：JSON Lines，按大小滚动，线程安全。

只记录「谁在什么时候访问了什么、结果如何、花了多久」，不记录任何密钥。
"""
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "access.log"
MAX_BYTES = 5 * 1024 * 1024   # 单文件 5MB
KEEP = 5                      # 保留 5 个历史文件

_lock = threading.Lock()

_SENSITIVE = ("token", "password", "admin", "key", "secret", "x-admin-password")


def _sanitize_query(items: list[tuple[str, str]]) -> str:
    """去掉可能含密钥的查询参数，其余原样保留。"""
    safe = []
    for k, v in items:
        if any(s in k.lower() for s in _SENSITIVE):
            safe.append(f"{k}=<hidden>")
        else:
            safe.append(f"{k}={v}")
    return "&".join(safe)[:300]


def _rotate_if_needed() -> None:
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size >= MAX_BYTES:
            for i in range(KEEP - 1, 0, -1):
                src = LOG_DIR / f"access.log.{i}"
                dst = LOG_DIR / f"access.log.{i + 1}"
                if src.exists():
                    os.replace(src, dst)
            os.replace(LOG_FILE, LOG_DIR / "access.log.1")
    except OSError:
        pass


def write(entry: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    with _lock:
        try:
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            _rotate_if_needed()
        except OSError:
            pass


def log_request(*, ip: str, method: str, path: str, query: list[tuple[str, str]],
                status: int, ms: float, ua: str, referer: str) -> None:
    write({
        "t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "ts": round(time.time(), 3),
        "ip": ip,
        "method": method,
        "path": path,
        "query": _sanitize_query(query),
        "status": status,
        "ms": round(ms, 1),
        "ua": (ua or "")[:120],
        "ref": (referer or "")[:200],
    })


def tail(limit: int = 200, *, path_prefix: str = "", status: str = "",
         ip: str = "", files: int = 1) -> list[dict]:
    """从日志尾部读最近的若干条（默认只看当前文件）。"""
    out: list[dict] = []
    names = ["access.log"] + [f"access.log.{i}" for i in range(1, max(1, files) + 1)]
    for idx, name in enumerate(names):
        p = LOG_DIR / name
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if path_prefix and not str(e.get("path", "")).startswith(path_prefix):
                continue
            if status and str(e.get("status")) != str(status):
                continue
            if ip and ip not in str(e.get("ip", "")):
                continue
            out.append(e)
            if len(out) >= limit:
                return out
    return out
