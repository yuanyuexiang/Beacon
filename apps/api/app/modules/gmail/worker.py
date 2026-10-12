"""Single durable mail worker. No queued approvals => no send calls."""

import time

from app.core.db import get_sessionmaker
from app.modules.gmail import service


def main():
    last_sync = 0.0
    while True:
        try:
            with get_sessionmaker()() as db:
                service.tick(db)
            if time.monotonic() - last_sync > 60:
                with get_sessionmaker()() as db:
                    service.sync_replies(db)
                last_sync = time.monotonic()
        except Exception as error:
            # 不输出请求 URL、邮件、OAuth 响应或密钥。
            print(f"Gmail worker operation failed: {type(error).__name__}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
