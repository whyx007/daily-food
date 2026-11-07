"""把本地项目代码上传到 VPS（跳过 .git/.env/数据库等运行时文件）。

用法：python scripts/upload_to_vps.py
"""
import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("DSH_SSH_HOST", "43.133.86.206")
PORT = int(os.environ.get("DSH_SSH_PORT", "22"))
USER = os.environ.get("DSH_SSH_USER", "ubuntu")
PASSWORD = os.environ.get("DSH_SSH_PASSWORD", "")
REMOTE_ROOT = "/opt/daily-food"

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", ".conda-env", "docs", "deploy"}
SKIP_FILES = {".env", ".gitignore"}


def main() -> int:
    if not PASSWORD:
        print("DSH_SSH_PASSWORD not set")
        return 1
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15,
                   allow_agent=False, look_for_keys=False)

    files = []
    dirs = {REMOTE_ROOT}
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts and (rel.parts[0] in SKIP_DIRS or rel.parts[0].startswith(".chrome-tmp")):
            continue
        if path.name in SKIP_FILES:
            continue
        files.append((path, f"{REMOTE_ROOT}/{rel.as_posix()}"))
        dirs.add(f"{REMOTE_ROOT}/{rel.parent.as_posix()}")

    dir_list = " ".join(sorted(dirs))
    _, stdout, stderr = client.exec_command(f"mkdir -p {dir_list}", timeout=60)
    stdout.channel.recv_exit_status()
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        print("mkdir stderr:", err)

    sftp = paramiko.SFTPClient.from_transport(client.get_transport())
    for local, remote in files:
        sftp.put(str(local), remote)
        print(f"  up {Path(remote).name}")
    print(f"uploaded {len(files)} files -> {USER}@{HOST}:{REMOTE_ROOT}")
    sftp.close()
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
