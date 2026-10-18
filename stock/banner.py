# -*- coding: utf-8 -*-
"""控制台启动横幅：逐行打印 + 行情引擎进度（可在 server.py 里调用）。"""
import sys
import time

# ASCII 鲸鱼 + 蜡烛图，纯 ASCII 保证 cmd 里不乱码
WHALE = [
    "        .-\"\"\"\"-.            .-\"\"\"\"-.",
    "      .'  o    o'\\          /'o    o  '.",
    "     /      ^    \\        /    ^      \\",
    "    |   \\  ___  /|        |\\  ___  /   |",
    "     \\   \\_____/ /        \\ \\_____/   /",
    "      '.       .'          '.       .'",
    "        '-...-'              '-...-'",
]

CANDLES = [
    "   |            |            |",
    "  ███          ███          ███",
    "   |     ███    |     ███    |",
    "   |      |     |      |     |",
]


def banner(delay=0.045, animate=True):
    """打印启动横幅。delay=0 即瞬间打印（测试/脚本用）。"""
    lines = [
        "",
        "  ╔══════════════════════════════════════════════════════════╗",
        "  ║                                                          ║",
        "  ║      A 股 本 地 股 票 系 统        v1.0                  ║",
        "  ║      ─────────────────────────────────                   ║",
        "  ║      行情 · 自选 · 回测 · 账户 · 预警 · AI 建议          ║",
        "  ║                                                          ║",
        "  ╚══════════════════════════════════════════════════════════╝",
        "",
        "         /\\.                 行情引擎               .//\\",
        "        /   \\               深 海 数 据 中 心      /   \\",
        "       /  o  \\                                     /  o  \\",
        "      |   ^   |          ◢◤  ◢◤◤  ◢◤◤◤          |   ^   |",
        "       \\     /         ◢◤  ◢◤  ◢◤              \\     /",
        "        \\   /        ◢◤  ◢◤                   \\   /",
        "         \\_/                                    \\_/",
        "",
    ]
    if animate:
        for i, line in enumerate(lines):
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            if i < 8:
                time.sleep(delay)
        steps = ["载入配置", "唤醒行情引擎", "连接数据源", "同步自选股", "准备就绪"]
        for s in steps:
            sys.stdout.write("\r    ▸ %-14s" % (s + " …"))
            sys.stdout.flush()
            time.sleep(delay * 2.2)
        sys.stdout.write("\r    ▸ %-14s\n" % "准备就绪 ✓")
        sys.stdout.flush()
    else:
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    banner(animate=False)
