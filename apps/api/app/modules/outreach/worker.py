"""One durable social queue worker; no browser or social credentials in this process."""

import logging
import time

from app.core.db import get_sessionmaker
from app.modules.outreach.service import tick

logger = logging.getLogger(__name__)


def main():
    while True:
        try:
            with get_sessionmaker()() as db:
                tick(db)
        except Exception:
            # Do not log credentials, approval tokens, webhook bodies or upstream error payloads.
            logger.warning("社媒 worker 本轮未完成，将重试查询及未执行任务")
        time.sleep(5)


if __name__ == "__main__":
    main()
