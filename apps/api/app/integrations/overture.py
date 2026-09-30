"""Overture Maps Places：按边界框下载 GeoParquet（overturemaps-py，CDLA-Permissive-2.0 数据），本地缓存；
按距离 + 名称相似度匹配 FSA 门店，补官网/电话/社交。只保存许可允许的字段，并记录来源与置信度。"""

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STOP = {"the", "ltd", "limited", "restaurant", "cafe", "bar", "london", "kitchen", "and", "amp", "co", "uk"}


@dataclass
class Place:
    id: str
    name: str
    lon: float
    lat: float
    confidence: float | None
    websites: list[str]
    phones: list[str]
    socials: list[str]
    category: str | None
    postcode: str | None
    brand: str | None = None


def bbox_key(bbox: tuple[float, float, float, float]) -> str:
    return hashlib.sha256(json.dumps([round(x, 4) for x in bbox]).encode()).hexdigest()[:12]


def ensure_places(bbox: tuple[float, float, float, float], data_dir: Path, release: str | None = None) -> Path:
    """下载（或复用缓存）边界框内的 place 数据。返回 parquet 路径。"""
    out = data_dir / "overture" / f"place_{bbox_key(bbox)}.parquet"
    if out.exists():
        return out
    import pyarrow as pa
    import pyarrow.parquet as pq
    from overturemaps import core

    reader = (
        core.record_batch_reader("place", bbox) if release is None else core.record_batch_reader("place", bbox, release)
    )
    batches = list(reader)
    out.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_batches(batches) if batches else pa.table({"id": pa.array([], pa.string())})
    pq.write_table(tbl, out)
    (out.with_suffix(".meta.json")).write_text(
        json.dumps({"bbox": bbox, "rows": tbl.num_rows, "release": release or "latest"})
    )
    return out


def load_places(path: Path) -> list[Place]:
    import pyarrow.parquet as pq

    tbl = pq.read_table(path)
    if "geometry" not in tbl.column_names:
        return []
    out: list[Place] = []
    for r in tbl.to_pylist():
        try:
            lon, lat = struct.unpack_from("<dd", r["geometry"], 5)  # WKB Point (little-endian)
        except Exception:
            continue
        addr = (r.get("addresses") or [None])[0] or {}
        out.append(
            Place(
                id=r.get("id") or "",
                name=((r.get("names") or {}).get("primary")) or "",
                lon=lon,
                lat=lat,
                confidence=r.get("confidence"),
                websites=list(r.get("websites") or []),
                phones=list(r.get("phones") or []),
                socials=list(r.get("socials") or []),
                category=r.get("basic_category"),
                postcode=addr.get("postcode") if isinstance(addr, dict) else None,
                brand=(((r.get("brand") or {}).get("names") or {}).get("primary"))
                if isinstance(r.get("brand"), dict)
                else None,
            )
        )
    return out


def _brand(b: Any) -> str | None:
    if not isinstance(b, dict):
        return None
    names = b.get("names") or {}
    return names.get("primary") if isinstance(names, dict) else None


def _tokens(s: str) -> set[str]:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    return {t for t in s.split() if t not in STOP}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lon1 - lon2) * math.cos(math.radians(lat1)) * 111320, (lat1 - lat2) * 110540)


def match(
    name: str, lat: float, lon: float, places: list[Place], max_m: float = 200, min_sim: float = 0.5
) -> dict[str, Any] | None:
    best: tuple[float, float, Place] | None = None
    for p in places:
        d = distance_m(lat, lon, p.lat, p.lon)
        if d > max_m:
            continue
        s = similarity(name, p.name)
        if s >= min_sim and (best is None or (s, -d) > (best[0], -best[1])):
            best = (s, d, p)
    if best is None:
        return None
    s, d, p = best
    return {
        "place_id": p.id,
        "name": p.name,
        "similarity": round(s, 3),
        "distance_m": round(d),
        "confidence": p.confidence,
        "websites": p.websites,
        "phones": p.phones,
        "socials": p.socials,
        "category": p.category,
        "postcode": p.postcode,
        "brand": p.brand,
    }
