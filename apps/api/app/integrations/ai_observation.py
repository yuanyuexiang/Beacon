"""有界 AI 调用记录：不存提示词、原文、联系人或密钥。"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from app.core.config import get_settings


def recent() -> list[dict]:
    directory = get_settings().data_dir / "ai-calls"
    rows = []
    for path in sorted(directory.glob("*.json"), reverse=True)[:100]:
        try:
            rows.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return rows


@contextmanager
def observe(purpose: str, model: str, version: str):
    start = time.monotonic()
    row: dict = {"purpose": purpose, "model": model, "version": version, "usage": {}, "status": "succeeded"}
    try:
        yield row
    except Exception as exc:
        row["status"] = "failed"
        row["error_type"] = type(exc).__name__
        from app.integrations.llm import ProviderUnavailable

        if isinstance(exc, ProviderUnavailable):
            row["error"] = str(exc)[:500]
        else:
            row["error"] = "模型输出校验未通过，请检查输入资料或重试"
        raise
    finally:
        row["at"] = datetime.now(UTC).isoformat()
        row["duration_ms"] = round((time.monotonic() - start) * 1000)
        try:
            directory = get_settings().data_dir / "ai-calls"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{time.time_ns()}-{uuid.uuid4().hex}.json"
            with path.open("x") as output:
                os.chmod(path, 0o600)
                json.dump(row, output)
            for old in sorted(directory.glob("*.json"), reverse=True)[500:]:
                old.unlink(missing_ok=True)
        except OSError:
            pass
