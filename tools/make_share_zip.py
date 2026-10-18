# -*- coding: utf-8 -*-
"""打一个干净的分发包：递归排除 __pycache__ / 缓存 / 日志 / 旧 zip。"""
import os
import shutil
import sys
import tempfile
import zipfile

SRC = r"F:\My-Project\代码区\股票系统"
OUT = r"F:\My-Project\代码区\股票系统-分享版.zip"
ROOT_NAME = "股票系统"

SKIP_DIRS = {"__pycache__", "cache", ".git", "bin", "_backup"}
SKIP_EXT = {".zip", ".pyc", ".log", ".exe"}


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    stage = tempfile.mkdtemp(prefix="stock-zip-")
    root = os.path.join(stage, ROOT_NAME)
    os.makedirs(root)

    copied = skipped = 0
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, SRC)
        target_dir = root if rel == "." else os.path.join(root, rel)
        # data 目录：不留任何本机数据，只保留空壳
        if rel == "data" or rel.startswith("data" + os.sep):
            continue
        os.makedirs(target_dir, exist_ok=True)
        for name in filenames:
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                skipped += 1
                continue
            shutil.copy2(os.path.join(dirpath, name), os.path.join(target_dir, name))
            copied += 1
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    open(os.path.join(root, "data", ".keep"), "w").close()

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                full = os.path.join(dirpath, name)
                arc = os.path.relpath(full, stage).replace(os.sep, "/")
                z.write(full, arc)
    shutil.rmtree(stage, ignore_errors=True)

    size = os.path.getsize(OUT)
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
    need = ["server.py", "启动.cmd", "README.md", "stock/datasource.py",
            "static/app.js", "fixtures/MANIFEST.json", "requirements-none.txt"]
    print("压缩包: %s" % OUT)
    print("大小: %.2f MB | 条目 %d | 复制 %d 个文件（跳过 %d 个日志/zip）"
          % (size / 1024 / 1024, len(names), copied, skipped))
    for item in need[:-1]:
        print("  %-26s %s" % (item, "OK" if (ROOT_NAME + "/" + item) in names else "缺失"))
    bad = [n for n in names if "__pycache__" in n or n.endswith(".zip") or n.endswith(".pyc")]
    print("  误带缓存/压缩包:", bad or "无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
