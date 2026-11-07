"""把 scripts/deploy_vps.sh 上传到 VPS 并执行。

用法：python scripts/run_deploy.py
"""
import os
import sys

import paramiko

HOST = os.environ.get("DSH_SSH_HOST", "43.133.86.206")
PORT = int(os.environ.get("DSH_SSH_PORT", "22"))
USER = os.environ.get("DSH_SSH_USER", "ubuntu")
PASSWORD = os.environ.get("DSH_SSH_PASSWORD", "")
SCRIPT = os.path.join(os.path.dirname(__file__), "deploy_vps.sh")


def main() -> int:
    if not PASSWORD:
        print("DSH_SSH_PASSWORD not set")
        return 1
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15,
                   allow_agent=False, look_for_keys=False)
    sftp = paramiko.SFTPClient.from_transport(client.get_transport())
    sftp.put(SCRIPT, "/tmp/deploy_vps.sh")
    sftp.close()
    _, stdout, stderr = client.exec_command("bash /tmp/deploy_vps.sh", timeout=600)
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
