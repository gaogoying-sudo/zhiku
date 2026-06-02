#!/usr/bin/env python3
"""Clean sync script for Zhiku Dashboard using shell commands"""
import subprocess
import os

# Config
REMOTE_HOST = os.getenv("REMOTE_HOST", "")
REMOTE_PORT = os.getenv("REMOTE_PORT", "3306")
REMOTE_USER = os.getenv("REMOTE_USER", "")
REMOTE_PASS = os.getenv("REMOTE_PASS", "")

LOCAL_DB = os.getenv("LOCAL_DB", "zhiku_db")
LOCAL_USER = os.getenv("LOCAL_USER", "root")
LOCAL_PASS = os.getenv("LOCAL_PASS", "")
CONTAINER = os.getenv("CONTAINER", "zhiku-mysql")

if not all([REMOTE_HOST, REMOTE_USER, REMOTE_PASS, LOCAL_PASS]):
    raise SystemExit("请通过环境变量提供 REMOTE_HOST/REMOTE_USER/REMOTE_PASS/LOCAL_PASS")

tables = [
    ("btyc", "sop_robot"),
    ("btyc", "robot_conservation_pot_log"),
    ("btyc", "bytc_robot_malfunctions_log"),
    ("btyc", "robot_config_info"),
    ("manage_backend", "main_recipe")
]

print("🚀 开始同步智库数据库小表缓存...")
print("ℹ️ sop_machinelog 生产大表不再全量同步，API 会按 SN 直接查询公司只读库。")

for db, table in tables:
    print(f"📦 同步 {db}.{table} ...")
    # Dump from remote
    dump_cmd = (
        f"mysqldump -h {REMOTE_HOST} -P {REMOTE_PORT} -u {REMOTE_USER} -p'{REMOTE_PASS}' "
        f"--lock-tables=false --no-tablespaces --set-gtid-purged=OFF {db} {table} 2>/dev/null"
    )
    # Import to local docker
    import_cmd = f"sudo docker exec -i {CONTAINER} mysql -u{LOCAL_USER} -p'{LOCAL_PASS}' {LOCAL_DB}"

    full_cmd = f"{dump_cmd} | {import_cmd}"

    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Failed {db}.{table}: {result.stderr[:200]}")
    else:
        print(f"✅ 成功 {db}.{table}")

print("🎉 同步完成！")
