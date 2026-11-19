"""Bounded, owner-scoped APK staging. Each HTTP request carries at most 2 MiB."""

import fcntl
import json
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

CHUNK_BYTES = 2 * 1024**2
TTL = 3600


def root(folder: Path) -> Path:
    path = folder / "staging"
    path.mkdir(exist_ok=True)
    return path


def begin(folder: Path, owner: str, size: int) -> str:
    with (folder / ".staging.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _begin(root(folder), owner, size)


def _begin(staging: Path, owner: str, size: int) -> str:
    active = 0
    for item in staging.iterdir():
        try:
            if not item.is_dir():
                continue
            if item.stat().st_mtime < time.time() - TTL:
                shutil.rmtree(item, ignore_errors=True)
            elif (item / "meta.json").exists():
                meta = json.loads((item / "meta.json").read_text())
                active += meta["owner"] == owner
        except FileNotFoundError:
            # Another request can finish/cancel an upload during this scan.
            continue
    if active >= 4:
        raise HTTPException(409, "已有多个未完成上传，请稍后重试")
    identity = str(uuid.uuid4())
    path = staging / identity
    path.mkdir(mode=0o700)
    (path / "data.apk").touch(mode=0o600)
    pending = path / "meta.tmp"
    pending.write_text(json.dumps({"owner": owner, "size": size}))
    pending.replace(path / "meta.json")
    return identity


@contextmanager
def locked(folder: Path, identity: uuid.UUID, owner: str):
    path = root(folder) / str(identity)
    try:
        handle = (path / "meta.json").open()
    except FileNotFoundError as exc:
        raise HTTPException(404, "上传已过期或不存在，请重新上传") from exc
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HTTPException(409, "该安装包正在处理，请稍后重试") from exc
        meta = json.load(handle)
        if meta["owner"] != owner:
            raise HTTPException(404, "上传不存在")
        if not path.exists() or path.stat().st_mtime < time.time() - TTL:
            raise HTTPException(410, "上传已过期，请重新上传")
        path.touch()
        yield path, meta


def append(path: Path, total: int, offset: int, body: bytes) -> int:
    target = path / "data.apk"
    received = target.stat().st_size
    if not body or len(body) > CHUNK_BYTES or offset < 0 or offset + len(body) > total:
        raise HTTPException(422, "上传分段大小或位置无效")
    # Lost responses can be retried without duplicating bytes.
    if offset < received and offset + len(body) <= received:
        with target.open("rb") as stream:
            stream.seek(offset)
            if stream.read(len(body)) == body:
                return received
    if offset != received:
        raise HTTPException(409, "上传位置不一致，请重新上传")
    with target.open("ab") as stream:
        stream.write(body)
    return offset + len(body)
