"""提取质量提示不是菜单设计缺陷，不自动标记事实审核通过。"""

from collections import Counter


def assess(items: list[dict]) -> dict:
    warnings = []
    if not items:
        warnings.append("未提取到菜品，请核对文件是否为菜单或改用 AI 识别")
    missing = [
        i + 1 for i, item in enumerate(items) if not str(item.get("name") or "").strip() or not item.get("evidence")
    ]
    if missing:
        warnings.append("部分条目缺少名称或来源定位")
    names = Counter(str(item.get("name") or "").strip().casefold() for item in items)
    duplicate = [i + 1 for i, item in enumerate(items) if names[str(item.get("name") or "").strip().casefold()] > 1]
    if duplicate:
        warnings.append("存在重复菜名，请核对是否不同规格或重复提取")
    return {
        "version": "quality-1",
        "status": "review" if warnings else "no_obvious_anomaly",
        "warnings": warnings,
        "item_numbers": sorted(set(missing + duplicate)),
        "note": "仅检查提取完整性，不代表菜名、价格准确或已完成事实核对",
    }
