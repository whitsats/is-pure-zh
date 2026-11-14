"""Build the native Android prototype offline with a local Android SDK and JDK.

Usage: python build.py
The resulting APK is signed with a local *test-only* key, not a release key.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "src" / "org" / "ispure" / "demo" / "MainActivity.java"
MANIFEST = ROOT / "AndroidManifest.xml"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"
MIN_SDK = "23"
TARGET_PLATFORM = "android-35"
OUTPUT = DIST / "ispure-native-demo.apk"
KEYSTORE = DIST / "test-only.keystore"


def sdk_directory() -> Path:
    candidates = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(str(Path(local_appdata) / "Android" / "Sdk"))
    for item in candidates:
        if item and (Path(item) / "platforms" / TARGET_PLATFORM / "android.jar").is_file():
            return Path(item)
    raise RuntimeError("未找到 Android SDK 的 platforms/android-35/android.jar；请设置 ANDROID_HOME。")


def build_tools(sdk: Path) -> Path:
    parent = sdk / "build-tools"
    if not parent.is_dir():
        raise RuntimeError(f"未找到 Android SDK build-tools: {parent}")
    folders = [p for p in parent.iterdir() if p.is_dir() and re.fullmatch(r"\d+(?:\.\d+)*", p.name)]
    folders.sort(key=lambda p: tuple(map(int, p.name.split("."))), reverse=True)
    suffix = ".exe" if os.name == "nt" else ""
    for folder in folders:
        if all((folder / p).is_file() for p in (f"aapt{suffix}", f"zipalign{suffix}", "lib/d8.jar", "lib/apksigner.jar")):
            return folder
    raise RuntimeError(f"{parent} 中没有完整的 aapt、D8、zipalign 和 apksigner。")


def jdk_command(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / f"{name}{suffix}"
        if candidate.is_file():
            return str(candidate)
    command = shutil.which(name)
    if command:
        return command
    raise RuntimeError(f"未找到 {name}，请设置 JAVA_HOME 指向 JDK。")


def run(label: str, command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"\n[{label}]", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    if not SOURCE.is_file():
        raise RuntimeError(f"未找到入口源码: {SOURCE}")
    if not MANIFEST.is_file() or not ASSETS.is_dir():
        raise RuntimeError("缺少 AndroidManifest.xml 或 assets 文件夹。")
    sdk = sdk_directory()
    tools = build_tools(sdk)
    android_jar = sdk / "platforms" / TARGET_PLATFORM / "android.jar"
    exe = ".exe" if os.name == "nt" else ""
    java, javac, keytool = (jdk_command(name) for name in ("java", "javac", "keytool"))
    DIST.mkdir(exist_ok=True)
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    if not KEYSTORE.exists():
        run("创建本地测试签名（仅供验证）", [keytool, "-genkeypair", "-keystore", str(KEYSTORE),
            "-storepass", "android", "-keypass", "android", "-alias", "androiddebugkey",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-dname", "CN=Android Debug,O=Local Test,C=US", "-storetype", "JKS"])
    with tempfile.TemporaryDirectory(prefix="apk-", dir=build_root) as tmp:
        work = Path(tmp).resolve()
        if not work.is_relative_to(build_root.resolve()):
            raise RuntimeError("临时目录不在项目构建目录内。")
        classes, dex = work / "classes", work / "dex"
        classes.mkdir()
        dex.mkdir()
        sources = sorted((ROOT / "src").rglob("*.java"))
        run("编译 Java", [javac, "-encoding", "UTF-8", "-source", "8", "-target", "8",
            "-classpath", str(android_jar), "-d", str(classes), *map(str, sources)])
        class_files = sorted(classes.rglob("*.class"))
        if not class_files:
            raise RuntimeError("Java 编译后未找到 class 文件。")
        run("转换 Android DEX", [java, "-cp", str(tools / "lib" / "d8.jar"),
            "com.android.tools.r8.D8", "--lib", str(android_jar), "--min-api", MIN_SDK,
            "--output", str(dex), *map(str, class_files)])
        unsigned, aligned = work / "unsigned.apk", work / "aligned.apk"
        run("打包资源", [str(tools / f"aapt{exe}"), "package", "-f", "-M", str(MANIFEST),
            "-I", str(android_jar), "-A", str(ASSETS), "-F", str(unsigned)])
        with ZipFile(unsigned, "a", ZIP_DEFLATED) as apk:
            dex_files = sorted(dex.glob("classes*.dex"))
            if not dex_files:
                raise RuntimeError("D8 未生成 classes.dex。")
            for dex_file in dex_files:
                apk.write(dex_file, dex_file.name)
        run("对齐 APK", [str(tools / f"zipalign{exe}"), "-f", "4", str(unsigned), str(aligned)])
        signer = [java, "-jar", str(tools / "lib" / "apksigner.jar")]
        signed = work / "signed.apk"
        run("测试签名", [*signer, "sign", "--ks", str(KEYSTORE), "--ks-key-alias", "androiddebugkey",
            "--ks-pass", "pass:android", "--key-pass", "pass:android", "--v4-signing-enabled", "false",
            "--out", str(signed), str(aligned)])
        run("验证签名", [*signer, "verify", "--verbose", str(signed)])
        shutil.copyfile(signed, OUTPUT)
        # aapt's dump path handling on Windows can reject non-ASCII absolute
        # paths. An ASCII filename relative to the output directory avoids it.
        run("验证 APK 信息", [str(tools / f"aapt{exe}"), "dump", "badging", OUTPUT.name], cwd=DIST)
    print(f"\n构建成功：{OUTPUT}\n签名仅用于本地测试。")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\n构建失败：{exc}", file=sys.stderr)
        sys.exit(1)
