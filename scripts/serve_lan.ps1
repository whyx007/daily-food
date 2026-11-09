# 局域网启动脚本：把服务绑到 0.0.0.0，同一 WiFi 下的手机/平板可直接访问。
# 用法：pwsh -File scripts\serve_lan.ps1          （默认端口 8123）
#      pwsh -File scripts\serve_lan.ps1 -Port 9000
param(
    [int]$Port = 8123,
    [string]$Python = "D:\Miniconda3\envs\daily-food\python.exe"
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $Python) { Write-Host "找不到 python，请用 -Python 指定解释器路径"; exit 1 }
}

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
    Select-Object -ExpandProperty IPAddress

Write-Host "服务启动中（$Python）"
Write-Host "本机访问：  http://127.0.0.1:$Port"
foreach ($ip in $ips) { Write-Host "局域网访问：http://${ip}:$Port" }
Write-Host "（手机需与本机连同一个 WiFi；浏览器不给 http 页面定位权限，可用右键地图设置出发点）"
Write-Host ""

& $Python -m uvicorn app.main:app --host 0.0.0.0 --port $Port --log-level warning
