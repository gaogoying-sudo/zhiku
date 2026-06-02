#!/bin/bash
# Sync DB Script: TencentDB -> Local Docker MySQL

# Config
REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_PORT="${REMOTE_PORT:-3306}"
REMOTE_USER="${REMOTE_USER:-}"
REMOTE_PASS="${REMOTE_PASS:-}"

LOCAL_PORT="${LOCAL_PORT:-3308}"
LOCAL_USER="${LOCAL_USER:-root}"
LOCAL_PASS="${LOCAL_PASS:-}"
LOCAL_DB="${LOCAL_DB:-zhiku_db}"

if [ -z "$REMOTE_HOST" ] || [ -z "$REMOTE_USER" ] || [ -z "$REMOTE_PASS" ] || [ -z "$LOCAL_PASS" ]; then
  echo "请通过环境变量提供 REMOTE_HOST/REMOTE_USER/REMOTE_PASS/LOCAL_PASS"
  exit 1
fi

DUMP_FILE="/tmp/zhiku_sync.sql"

echo "🚀 开始同步智库数据库..."
echo "ℹ️ sop_machinelog 生产大表不再全量同步，API 会按 SN 直接查询公司只读库。"

# 1. Dump from Remote
echo "USE zhiku_db;" > $DUMP_FILE
mysqldump -h $REMOTE_HOST -P $REMOTE_PORT -u $REMOTE_USER -p$REMOTE_PASS \
  --lock-tables=false \
  --no-tablespaces \
  --set-gtid-purged=OFF \
  btyc sop_robot robot_conservation_pot_log bytc_robot_malfunctions_log robot_config_info \
  2>/dev/null >> $DUMP_FILE

if [ $? -ne 0 ]; then
  echo "❌ Remote dump failed"
  exit 1
fi

echo "📦 Dump completed. Size: $(du -h $DUMP_FILE | cut -f1)"

# 3. Load to Local
mysql -h 127.0.0.1 -P $LOCAL_PORT -u $LOCAL_USER -p$LOCAL_PASS $LOCAL_DB < $DUMP_FILE

if [ $? -ne 0 ]; then
  echo "❌ Local import failed"
  exit 1
fi

# 4. Sync main_recipe from manage_backend
mysqldump -h $REMOTE_HOST -P $REMOTE_PORT -u $REMOTE_USER -p$REMOTE_PASS \
  --lock-tables=false \
  --no-tablespaces \
  --set-gtid-purged=OFF \
  manage_backend main_recipe \
  2>/dev/null >> $DUMP_FILE

mysql -h 127.0.0.1 -P $LOCAL_PORT -u $LOCAL_USER -p$LOCAL_PASS $LOCAL_DB < $DUMP_FILE

echo "✅ 同步完成！"
rm $DUMP_FILE
