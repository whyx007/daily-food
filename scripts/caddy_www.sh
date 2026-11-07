#!/usr/bin/env bash
set -e
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%s)

if grep -q "www.whyx.site" /etc/caddy/Caddyfile; then
  echo "www.whyx.site already configured, skip"
else
  # 在 :80 默认站点块之前插入 www.whyx.site 站点块（Caddy 具体域名优先于通配 :80）
  sudo sed -i '1i www.whyx.site:80 {\n    reverse_proxy localhost:9000\n}\n' /etc/caddy/Caddyfile
  echo "caddyfile updated"
fi

sudo systemctl reload caddy || sudo systemctl restart caddy
sleep 2
sudo systemctl status caddy --no-pager | head -6
echo "---"
sudo cat /etc/caddy/Caddyfile | head -8
