"""Inspect untrusted APKs with Android's signature verifier and resource tools; never install/run them."""

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from fastapi import HTTPException

PACKAGE = "com.beacon.mobile"


def tool(name: str) -> str | None:
    override = os.environ.get("BEACON_" + name.upper())
    if override:
        return override if Path(override).is_file() else None
    installed = shutil.which(name)
    if installed:
        return installed
    sdk = Path(
        os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "Library/Android/sdk"
    )
    choices = sorted((sdk / "build-tools").glob(f"*/{name}"), reverse=True)
    return str(choices[0]) if choices else None


def available() -> bool:
    return bool(tool("apksigner") and (tool("aapt2") or tool("aapt")))


def output(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(422, "安装包校验未完成，请检查文件或联系管理员检查 Android 校验工具") from exc
    if result.returncode:
        raise HTTPException(422, "APK 签名或内容校验失败，文件可能损坏、未签名或不是可安装的完整安装包")
    return result.stdout


def inspect(path: Path) -> dict:
    signer, aapt = tool("apksigner"), tool("aapt2") or tool("aapt")
    if not signer or not aapt:
        raise HTTPException(503, "服务器未配置 Android 安装包校验工具，请联系技术方；当前发布版本不受影响")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if names.count("AndroidManifest.xml") != 1 or "classes.dex" not in names:
                raise ValueError("not a standalone APK")
            if len(entries) > 50000 or sum(e.file_size for e in entries) > 1024**3:
                raise ValueError("oversized archive")
            if archive.getinfo("AndroidManifest.xml").file_size > 4 * 1024**2:
                raise ValueError("oversized manifest")
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(422, "请上传完整、有效的 APK 文件，不支持 AAB、拆分安装包或普通 ZIP") from exc
    certificates = output([signer, "verify", "--print-certs", str(path)])
    fingerprints = set(
        re.findall(r"(?m)^(?:Signer #\d+|V[\d.]+ Signer):? certificate SHA-256 digest: ([a-fA-F0-9]{64})", certificates)
    )
    if len(fingerprints) != 1:
        raise HTTPException(422, "无法确认安装包的单一签名证书")
    manifest = output([aapt, "dump", "badging", str(path)])
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", manifest, re.M)
    if not package or package[1] != PACKAGE:
        raise HTTPException(422, "安装包不是 Beacon 手机助手，请检查包名 com.beacon.mobile")
    if "application-debuggable" in manifest or "application-testOnly" in manifest:
        raise HTTPException(422, "请上传 release 安装包，不支持调试或 testOnly 安装包")
    if not package[3] or not 0 < int(package[2]) <= 2**31 - 1:
        raise HTTPException(422, "安装包版本信息无效")
    return {
        "package": PACKAGE,
        "version_code": int(package[2]),
        "version_name": package[3],
        "signer_sha256": next(iter(fingerprints)).lower(),
        "development_signature": "CN=Android Debug" in certificates,
    }
