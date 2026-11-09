"""用 git bundle 把本地提交同步到 VPS，然后用 Docker 重新启动服务。

流程：
  1. 本地 git bundle create（纯 git 传输，绕开 GitHub 网络问题）；
  2. SFTP 上传 bundle；
  3. 远端：停旧 systemd 服务 -> 迁移 SQLite 到 data-store/ -> git fetch bundle + reset --hard
     -> 更新 .env 半径档位 -> docker compose 构建并启动；
  4. 校验容器内的 /api/health。

用法：
    python scripts/deploy_docker.py            # 完整部署
    python scripts/deploy_docker.py --dry      # 只看远端现状，不动任何东西
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get("DSH_SSH_HOST", "43.133.86.206")
PORT = int(os.environ.get("DSH_SSH_PORT", "22"))
USER = os.environ.get("DSH_SSH_USER", "ubuntu")
PASSWORD = os.environ.get("DSH_SSH_PASSWORD", "")

REMOTE = "/opt/daily-food"
BUNDLE = "/tmp/daily-food.bundle"
BRANCH = "main"
RADIUS = "3000,5000,15000"


def run(client, cmd, timeout=900, sudo=False, quiet=False):
    real = f"sudo -n bash -lc {shell_quote(cmd)}" if sudo else f"bash -lc {shell_quote(cmd)}"
    stdin, stdout, stderr = client.exec_command(real, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if not quiet:
        print((out + err).rstrip())
    if code != 0:
        print(f"[exit {code}] {cmd[:80]}")
    return code, out, err


def shell_quote(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


def main():
    dry = "--dry" in sys.argv

    # 1. 本地打 bundle
    import subprocess
    bundle_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "daily-food.bundle")
    print(f"==> 本地生成 bundle: {bundle_path}")
    code = subprocess.call(["git", "bundle", "create", bundle_path, BRANCH],
                           cwd=os.path.dirname(bundle_path))
    if code != 0:
        print("bundle 生成失败")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=20,
                   allow_agent=False, look_for_keys=False)

    if dry:
        print("==> 远端现状")
        run(client, f"cd {REMOTE} && git log --oneline -1; systemctl is-active daily-food; docker ps -a | head -5")
        client.close()
        return 0

    # 2. 上传 bundle
    print("==> 上传 bundle")
    sftp = client.open_sftp()
    sftp.put(bundle_path, BUNDLE)
    sftp.close()
    run(client, f"ls -lh {BUNDLE}")

    # 3. 停旧服务
    print("==> 停止旧 systemd 服务")
    run(client, "systemctl stop daily-food 2>/dev/null; systemctl disable daily-food 2>/dev/null; systemctl is-active daily-food", sudo=True)

    # 4. 迁移 SQLite（停服后复制，保证一致）
    print("==> 迁移数据库到 data-store/")
    run(client,
        f"cd {REMOTE} && mkdir -p data-store && "
        f"for f in daily-food.db daily-food.db-wal daily-food.db-shm; do "
        f"  [ -f $f ] && cp -a $f data-store/ || true; done; "
        f"ls -lh data-store",
        sudo=True)

    # 5. 用 bundle 同步代码
    print("==> git bundle 同步代码")
    run(client,
        f"cd {REMOTE} && git fetch {BUNDLE} {BRANCH} 2>&1 | tail -3 && "
        f"git reset --hard FETCH_HEAD && git log --oneline -1 && git status --short | head -10",
        sudo=True)

    # 6. 更新半径档位
    print("==> 更新 .env 半径档位")
    run(client,
        f"cd {REMOTE} && sed -i 's/^RADIUS_OPTIONS=.*/RADIUS_OPTIONS={RADIUS}/' .env && "
        f"grep -E 'RADIUS_OPTIONS|DEFAULT_LAT|DEFAULT_LNG' .env",
        sudo=True)

    # 7. 构建并启动容器
    print("==> docker compose 构建（可能需要几分钟）")
    code, out, err = run(client, f"cd {REMOTE} && docker compose build 2>&1 | tail -25", timeout=1200, sudo=True)
    if code != 0:
        print("构建失败，停在旧服务已停止的状态")
        client.close()
        return 1

    print("==> 启动容器")
    run(client, f"cd {REMOTE} && docker compose up -d 2>&1 | tail -15", timeout=300, sudo=True)

    # 8. 等待健康
    print("==> 等待容器健康")
    for i in range(30):
        code, out, _ = run(client, "curl -sS -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9000/api/health", quiet=True)
        if out.strip() == "200":
            print(f"健康检查通过（第 {i + 1} 次）")
            break
        time.sleep(3)
    else:
        print("健康检查超时，输出容器日志")
        run(client, f"cd {REMOTE} && docker compose logs --tail 40", sudo=True)

    print("==> 状态汇总")
    run(client, f"cd {REMOTE} && docker compose ps; systemctl is-active daily-food; df -h / | tail -1", sudo=True)
    client.close()
    try:
        os.remove(bundle_path)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
