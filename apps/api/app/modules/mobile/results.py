"""Bounded execution screenshots; never exposed in list or device payloads."""

import base64
import io

from PIL import Image


def screenshot_jpeg(value: str) -> str:
    try:
        raw = base64.b64decode(value, validate=True)
        with Image.open(io.BytesIO(raw)) as picture:
            if picture.format not in {"JPEG", "PNG"} or not (
                1 <= picture.width <= 1600 and 1 <= picture.height <= 2400
            ):
                raise ValueError("invalid dimensions")
            picture.load()
            picture.thumbnail((720, 1600))
            output = io.BytesIO()
            picture.convert("RGB").save(output, format="JPEG", quality=70)
        return base64.b64encode(output.getvalue()).decode("ascii")
    except Exception as exc:
        raise ValueError("执行截图必须是有效且尺寸受限的 JPEG 或 PNG 图片") from exc
