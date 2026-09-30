#!/usr/bin/env bash
# 备份：数据库（pg_dump 自定义格式）+ 受控数据目录（tar）。用法：infra/backup.sh <BEACON_DATA_DIR> [备份目录]
set -euo pipefail
DATA_DIR="${1:?用法: backup.sh <BEACON_DATA_DIR> [备份目录]}"
OUT="${2:-backups}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
docker exec beacon-postgres pg_dump -U beacon -Fc beacon > "$OUT/beacon-$TS.dump"
if [ -d "$DATA_DIR" ]; then tar -czf "$OUT/data-$TS.tgz" -C "$DATA_DIR" .; else echo "数据目录不存在：$DATA_DIR（跳过文件备份）"; fi
shasum -a 256 "$OUT"/*-"$TS".*
echo "backup done: $OUT/*-$TS.*"
