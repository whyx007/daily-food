"""在 VPS 上执行命令（命令经 base64 传输，避免引号转义问题）。

用法：python scripts/vps_cmd.py "<command>"
"""
import base64
import os
import sys

import paramiko

HOST = os.environ.get("DSH_SSH_HOST", "43.133.86.206")
PORT = int(os.environ.get("DSH_SSH_PORT", "22"))
USER = os.environ.get("DSH_SSH_USER", "ubuntu")
PASSWORD = os.environ.get("DSH_SSH_PASSWORD", "")

COMMAND = sys.argv[1]


def main() -> int:
    if not PASSWORD:
        print("DSH_SSH_PASSWORD not set")
        return 1
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15,
                   allow_agent=False, look_for_keys=False)
    b64 = base64.b64encode(COMMAND.encode("utf-8")).decode("ascii")
    _, stdout, stderr = client.exec_command(f"echo {b64} | base64 -d | bash", timeout=600)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    print(out)
    if err.strip():
        print("[stderr]", err)
    print(f"[exit {code}]")
    client.close()
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
