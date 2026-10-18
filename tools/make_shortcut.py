# -*- coding: utf-8 -*-
"""在桌面创建带图标的快捷方式（Windows）。

用法：
    python tools/make_shortcut.py            # 桌面
    python tools/make_shortcut.py --name 自定义名字

原理：通过 PowerShell 的 WScript.Shell 写 .lnk，目标指向本目录的 启动.cmd（桌面版），
图标用本目录的 icon.ico。
"""
import argparse
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(BASE, "启动.cmd")
ICON = os.path.join(BASE, "icon.ico")


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="股票系统")
    args = ap.parse_args(argv)

    if not os.path.exists(TARGET):
        print("找不到 %s" % TARGET)
        return 1
    if not os.path.exists(ICON):
        print("找不到图标 %s" % ICON)
        return 1

    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$desk = [Environment]::GetFolderPath('Desktop'); "
        "$path = Join-Path $desk " + ps_quote(args.name + ".lnk") + "; "
        "$l = $ws.CreateShortcut($path); "
        "$l.TargetPath = " + ps_quote(TARGET) + "; "
        "$l.WorkingDirectory = " + ps_quote(BASE) + "; "
        "$l.IconLocation = " + ps_quote(ICON + ",0") + "; "
        "$l.Description = 'A股本地股票系统'; "
        "$l.WindowStyle = 1; "
        "$l.Save(); "
        "Write-Output $path"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
    )
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    err = (proc.stderr or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not out:
        print("创建失败：", err or out or ("exit %d" % proc.returncode))
        return 1
    print("已创建桌面快捷方式：%s" % out)
    print("  目标：%s" % TARGET)
    print("  图标：%s" % ICON)
    return 0


if __name__ == "__main__":
    sys.exit(main())
