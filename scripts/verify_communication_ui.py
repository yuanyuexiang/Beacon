"""兼容旧验收命令；任务卡片布局已由客户连续会话替代。全部 API 模拟。"""

import asyncio

from verify_customer_conversations_ui import main

if __name__ == "__main__":
    asyncio.run(main())
