"""受控文件：所有文件相对 BEACON_DATA_DIR 存放；解析时拒绝越出目录的路径。"""

import hashlib
from pathlib import Path

from app.core.config import get_settings


class UnsafePathError(ValueError):
    pass


def data_dir() -> Path:
    d = get_settings().data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_within(rel: str) -> Path:
    base = data_dir().resolve()
    p = (base / rel).resolve()
    if p != base and base not in p.parents:
        raise UnsafePathError(f"路径越出数据目录：{rel}")
    return p


def store_bytes(rel: str, content: bytes) -> tuple[Path, str]:
    p = resolve_within(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p, hashlib.sha256(content).hexdigest()
