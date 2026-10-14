#!/bin/sh
set -eu
install -o maps -g maps -m 600 /run/secrets/maps_worker_token /tmp/maps-worker-token
chown maps:maps /data
exec gosu maps xvfb-run -a -s "-screen 0 1440x1000x24" python /srv/scripts/maps_menu_worker.py \
  --api-base "$MAPS_API_BASE" \
  --token-file /tmp/maps-worker-token \
  --profile /data/profile --temp-dir /data/tmp --proxy "" \
  --heartbeat-file /tmp/maps-heartbeat
