"""通过 SSH 在远端执行命令（供部署排查用）。

用法：python scripts/ssh_run.py "命令"   （密码从环境变量 DSH_SSH_PASSWORD 读取）
"""
import os
import sys

import paramiko

HOST = os.environ.get("DSH_SSH_HOST", "43.133.86.206")
PORT = int(os.environ.get("DSH_SSH_PORT", "22"))
USER = os.environ.get("DSH_SSH_USER", "root")
PASSWORD = os.environ.get("DSH_SSH_PASSWORD", "")

COMMAND = sys.argv[1] if len(sys.argv) > 1 else "id; uname -a"


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15,
                   allow_agent=False, look_for_keys=False)
    stdin, stdout, stderr = client.exec_command(COMMAND, timeout=60)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    print(out)
    if err.strip():
        print("[stderr]", err)
    print(f"[exit {code}]")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
