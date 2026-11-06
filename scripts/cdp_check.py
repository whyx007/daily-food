"""用 Chrome DevTools Protocol 检查页面里 AMap 是否真的初始化成功。

用法：先启动 chrome --headless=new --remote-debugging-port=9223 --remote-allow-origins=* <url>，
再执行 python scripts/cdp_check.py [http://127.0.0.1:9223]
"""
import json
import sys
import time

import httpx
from websockets.sync.client import connect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9223"

EXPR = """JSON.stringify({
  amap: typeof window.AMap,
  container: !!document.querySelector('.amap-container'),
  canvas: !!document.querySelector('.amap-container canvas'),
  items: document.querySelectorAll('.item').length,
  fallbackShown: !document.querySelector('#map-fallback').hidden,
  fallbackImg: !!document.querySelector('#map-fallback img'),
  pick: (document.querySelector('#daily-card .name') || {}).textContent || '',
  notice: (document.querySelector('#daily-card .notice') || {}).textContent || ''
})"""


def main() -> int:
    targets = httpx.get(f"{BASE}/json/list", timeout=5).json()
    page = next((t for t in targets if t.get("type") == "page"), None)
    if page is None:
        print("no page target")
        return 1

    with connect(page["webSocketDebuggerUrl"], open_timeout=10, close_timeout=5) as ws:
        ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        time.sleep(0.5)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                ws.recv(timeout=1)
            except TimeoutError:
                break

        time.sleep(8)
        ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                            "params": {"expression": EXPR, "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv(timeout=10))
            if msg.get("id") == 2:
                break
    result = msg["result"]["result"]
    print(result.get("value") or result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
