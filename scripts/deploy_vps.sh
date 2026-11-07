#!/usr/bin/env bash
set -e
cd /opt/daily-food

echo "==> installing python deps..."
./venv/bin/pip install -q --disable-pip-version-check fastapi uvicorn httpx pydantic pydantic-settings python-dotenv
./venv/bin/python - <<'PY'
import fastapi, pydantic, httpx
print("deps ok", fastapi.__version__, pydantic.VERSION, httpx.__version__)
PY

echo "==> installing systemd unit..."
sudo tee /etc/systemd/system/daily-food.service > /dev/null <<'UNIT'
[Unit]
Description=Daily Food API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/daily-food
EnvironmentFile=/opt/daily-food/.env
ExecStart=/opt/daily-food/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 9000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
echo "==> deploy script done"
