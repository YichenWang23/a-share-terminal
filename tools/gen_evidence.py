# -*- coding: utf-8 -*-
"""重新生成交付证据（全部 UTF-8，可被普通读取器当文本复查）。

用法：
    python tools/gen_evidence.py [--base http://127.0.0.1:8770]

产物（都在 docs/）：
    unit-tests.log    完整的 unittest -v 输出（含每个用例名）
    numbers-check.log 关键数字独立重算输出
    smoke-api.log     接口冒烟输出（服务在跑时才生成）
    selfcheck.log     一键自检输出
    EVIDENCE.md       证据清单：时间、测试数、各日志 SHA256
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent.parent
DOCS = BASE / "docs"
PY = sys.executable


def run(args):
    proc = subprocess.run(args, cwd=str(BASE), capture_output=True)
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    return proc.returncode, out, err


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def count_tests(text):
    for line in text.splitlines():
        if line.startswith("Ran ") and " test" in line:
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    args = ap.parse_args()
    DOCS.mkdir(exist_ok=True)
    summary = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": {}}

    def save(name, text):
        path = DOCS / name
        path.write_text(text, encoding="utf-8", newline="\n")
        summary["files"][name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        return path

    code, out, err = run([PY, "-m", "unittest", "discover", "-s", "tests", "-v"])
    save("unit-tests.log", out + err)
    summary["unit_tests"] = {"exit": code, "count": count_tests(out + err)}
    print("单元测试: exit=%d  %s 项" % (code, summary["unit_tests"]["count"]))

    code, out, err = run([PY, "tools/verify_numbers.py"])
    save("numbers-check.log", out + err)
    summary["numbers_check"] = {"exit": code}
    print("独立重算: exit=%d" % code)

    # 服务在跑才录冒烟
    alive = False
    try:
        with urllib.request.urlopen(args.base.rstrip("/") + "/api/health", timeout=5) as r:
            alive = r.status == 200
    except Exception:  # noqa: BLE001
        alive = False
    if alive:
        code, out, err = run([PY, "tools/smoke_api.py", "--base", args.base])
        save("smoke-api.log", out + err)
        summary["smoke"] = {"exit": code}
        print("接口冒烟: exit=%d" % code)
    else:
        summary["smoke"] = {"exit": None, "note": "服务未运行，跳过"}
        print("接口冒烟: 服务未运行，跳过")

    code, out, err = run([PY, "tools/selfcheck.py"])
    save("selfcheck.log", out + err)
    summary["selfcheck"] = {"exit": code}
    print("一键自检: exit=%d" % code)

    lines = [
        "# 交付证据清单",
        "",
        "生成时间：%s" % summary["generated_at"],
        "",
        "| 文件 | 字节 | SHA256 |",
        "| --- | --- | --- |",
    ]
    for name, info in summary["files"].items():
        lines.append("| `docs/%s` | %d | `%s` |" % (name, info["bytes"], info["sha256"]))
    lines += [
        "",
        "## 关键计数",
        "",
        "- 单元测试：**%s 项**（exit=%s）" % (summary["unit_tests"]["count"], summary["unit_tests"]["exit"]),
        "- 关键数字独立重算：exit=%s" % summary["numbers_check"]["exit"],
        "- 接口冒烟：%s" % (
            "exit=%s" % summary["smoke"]["exit"] if summary["smoke"].get("exit") is not None
            else summary["smoke"].get("note", "跳过")),
        "- 一键自检：exit=%s" % summary["selfcheck"]["exit"],
        "",
        "所有日志均为 UTF-8 纯文本，可直接 `Get-Content` / `cat` 复查。",
    ]
    save("EVIDENCE.md", "\n".join(lines) + "\n")
    print("已写 docs/EVIDENCE.md")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
