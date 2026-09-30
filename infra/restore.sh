#!/usr/bin/env bash
# 恢复演练：把 dump 恢复到指定数据库名（默认 beacon_restore_drill），并把文件包解到指定目录。
# 用法：infra/restore.sh <dump 文件> [目标库名] [文件包] [目标目录]
set -euo pipefail
DUMP="${1:?用法: restore.sh <dump> [目标库] [tgz] [目录]}"
DB="${2:-beacon_restore_drill}"
TGZ="${3:-}"
DIR="${4:-}"
docker exec beacon-postgres psql -U beacon -d postgres -qc "DROP DATABASE IF EXISTS $DB;" -c "CREATE DATABASE $DB OWNER beacon;"
docker exec -i beacon-postgres pg_restore -U beacon -d "$DB" --no-owner < "$DUMP"
docker exec beacon-postgres psql -U beacon -d "$DB" -Atc "select count(*) from information_schema.tables where table_schema='public';" | sed 's/^/tables restored: /'
if [ -n "$TGZ" ] && [ -n "$DIR" ]; then mkdir -p "$DIR"; tar -xzf "$TGZ" -C "$DIR"; echo "files restored to $DIR: $(find "$DIR" -type f | wc -l | tr -d ' ') files"; fi
echo "restore drill done into database $DB"
