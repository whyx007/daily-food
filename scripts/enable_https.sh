#!/usr/bin/env bash
set -e

echo "==> stopping xray..."
sudo pkill -f xray-linux-amd64 || echo "xray not running"
sleep 1
if sudo ss -tlnp | grep -q ':443 '; then
  echo "WARN: 443 still occupied:"
  sudo ss -tlnp | grep ':443 '
else
  echo "port 443 is now free"
fi

echo "==> enabling Caddy automatic HTTPS for www.whyx.site..."
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.https.$(date +%s)
sudo sed -i 's|^www\.whyx\.site:80 {|www.whyx.site {|' /etc/caddy/Caddyfile
sudo systemctl reload caddy || sudo systemctl restart caddy
sleep 3

echo "==> caddy status..."
sudo systemctl status caddy --no-pager | head -8
echo "==> listeners..."
sudo ss -tlnp | grep -E ':80 |:443 |:9000 ' || true
echo "==> caddyfile head..."
sudo head -5 /etc/caddy/Caddyfile
