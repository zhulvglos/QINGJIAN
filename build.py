# -*- coding: utf-8 -*-
"""
轻笺 (LightNote) — 打包构建脚本

依赖安装（仅首次）:
  pip install pyinstaller pefile altgraph pyinstaller-hooks-contrib

用法:
  python build.py              # 增量打包
  python build.py --clean      # 清理后重新打包
  python build.py --installer  # 同时生成 Inno Setup 安装包（需 iscc）

输出:
  dist/Qingjian.exe            # 单文件 exe (~14 MB)
  installer/轻笺_v0.4.0_安装包.exe  # 安装程序（--installer 时）
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"
# spec 文件放在项目父目录（避免中文路径导致 PyInstaller 找不到）
SPEC_FILE = PROJECT_ROOT.parent / "build_config.spec"


def clean():
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            shutil.rmtree(d)
            print(f"  [清理] {d}")
    spec = PROJECT_ROOT / "main.spec"
    if spec.exists():
        spec.unlink()
        print(f"  [清理] {spec.name}")


def build_exe():
    print("\n>>> PyInstaller 打包中...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "pyinstaller"),
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"\n打包失败 (exit code {result.returncode})")
        sys.exit(1)
    print("  [OK] PyInstaller 打包完成")


def post_process():
    exe_path = DIST_DIR / "Qingjian.exe"
    if not exe_path.exists():
        print(f"错误：未找到 {exe_path}")
        sys.exit(1)
    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"\n  =========================================")
    print(f"  输出文件: {exe_path.name}")
    print(f"  文件大小: {size_mb:.1f} MB")
    print(f"  输出目录: {DIST_DIR}")
    print(f"  =========================================")
    print(f"\n  直接双击运行: {exe_path}")
    print(f"  用户数据目录: %APPDATA%\\轻笺\\")


def build_installer():
    """调用 Inno Setup 生成安装程序"""
    iscc = shutil.which("iscc")
    if not iscc:
        # 常见安装路径
        for candidate in [
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            r"C:\Program Files\Inno Setup 6\ISCC.exe",
            r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        ]:
            if os.path.exists(candidate):
                iscc = candidate
                break

    if not iscc:
        print("\n[跳过] 未找到 Inno Setup，跳过安装程序生成")
        print("  安装 Inno Setup 6: https://jrsoftware.org/isdl.php")
        print("  安装后重新运行: python build.py --installer")
        return

    print("\n>>> Inno Setup 安装程序生成中...")
    iss_file = PROJECT_ROOT / "scripts" / "installer.iss"
    installer_dir = PROJECT_ROOT / "installer"
    installer_dir.mkdir(exist_ok=True)

    cmd = [iscc, str(iss_file), "/O" + str(installer_dir)]
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode == 0:
        print("  [OK] 安装程序已生成")
        for f in installer_dir.glob("*.exe"):
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  文件: {f.name} ({size_mb:.1f} MB)")
    else:
        print(f"\n安装程序生成失败 (exit code {result.returncode})")


def main():
    parser = argparse.ArgumentParser(description="轻笺打包工具")
    parser.add_argument("--clean", action="store_true", help="清理 build/ 和 dist/ 后重新打包")
    parser.add_argument("--installer", action="store_true", help="同时生成 Inno Setup 安装程序")
    args = parser.parse_args()

    print("=" * 50)
    print("  轻笺 (LightNote) - 打包工具")
    print("=" * 50)

    if args.clean:
        clean()

    DIST_DIR.mkdir(exist_ok=True)
    build_exe()
    post_process()

    if args.installer:
        build_installer()

    print("\n[完成]")


if __name__ == "__main__":
    main()
