"""持久化来源同步队列及定时调度；不处理销售任务或发送消息。"""

import logging
import threading
import time
from pathlib import Path

from app.core.db import get_sessionmaker
from app.modules.directory.models import WorkerStatus
from app.modules.directory.service import tick, utcnow


def heartbeat() -> None:
    while True:
        try:
            with get_sessionmaker()() as db:
                row = db.get(WorkerStatus, "directory")
                if row is None:
                    db.add(WorkerStatus(id="directory", heartbeat_at=utcnow()))
                else:
                    row.heartbeat_at = utcnow()
                db.commit()
            Path("/tmp/directory-heartbeat").touch()
        except Exception:
            logging.warning("门店池同步服务心跳暂不可用")
        time.sleep(15)


def main() -> None:
    threading.Thread(target=heartbeat, daemon=True).start()
    while True:
        try:
            with get_sessionmaker()() as db:
                worked = tick(db)
        except Exception:
            logging.warning("门店池 worker 本轮未完成，稍后恢复查询")
            worked = False
        time.sleep(1 if worked else 10)


if __name__ == "__main__":
    main()
