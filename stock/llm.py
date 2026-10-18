# -*- coding: utf-8 -*-
"""可选的真模型通道（OpenAI 兼容 /chat/completions）。

设计原则：
  * 默认关闭；没有 key 时永远走本地规则引擎，绝不伪造模型输出；
  * 调用失败/超时/返回异常，一律把错误原样带回去，由上层降级并标注原因；
  * 不在这里存 key（key 在 data/state.json 里，由用户自己填）。
"""
import json
import urllib.request

from . import secrets

SYSTEM_PROMPT = (
    "你是一位耐心的股市讲解员，读者是刚入市、看不懂术语的新手。\n"
    "硬性要求：\n"
    "1) 第一句必须是大白话结论（例如「短期偏弱，但还没到该慌的位置」），"
    "不要用「综上所述」「综合来看」开头。\n"
    "2) 然后给 2 到 3 条理由；每条先把术语翻译成人话，再说它的作用，"
    "例如「RSI 偏高＝最近涨得太急，短线容易回调」。\n"
    "3) 只使用给你的数据，不许编新闻、财报、评级或任何没给出的数字。\n"
    "4) 不要给「加仓/梭哈/满仓」这类操作指令，只描述状态和风险。\n"
    "5) 最后一行必须是风险提示，并声明不构成投资建议。\n"
    "6) 用中文，不用表情符号，不超过 300 字，多写短句。"
)


def build_prompt(context):
    """把结构化行情/指标/持仓压成一段可核查的提示词。"""
    lines = ["以下是某只 A 股的实时行情与技术指标（数据由本地程序抓取，可能滞后）：", ""]
    lines.append("【行情】")
    for key in ("name", "code", "price", "prev_close", "change_pct",
                "high", "low", "open", "volume", "limit_up", "limit_down", "timestamp"):
        if context.get(key) is not None:
            lines.append("  %s: %s" % (key, context[key]))
    metrics = context.get("metrics") or {}
    lines.append("")
    lines.append("【技术指标】")
    for key, value in metrics.items():
        lines.append("  %s: %s" % (key, value))
    if context.get("position"):
        lines.append("")
        lines.append("【我的持仓】")
        for key, value in context["position"].items():
            lines.append("  %s: %s" % (key, value))
    if context.get("rule_engine"):
        lines.append("")
        lines.append("【本地规则引擎的结论（可质疑）】")
        for bullet in context["rule_engine"].get("bullets", []):
            lines.append("  - " + bullet)
    lines.append("")
    lines.append("术语对照（讲的时候顺手用大白话解释，别直接甩名词）：")
    lines.append("  MA5/MA20/MA60＝最近 5/20/60 天的收盘价平均值；")
    lines.append("  RSI＝近 14 天涨跌力度，>70 偏热、<30 偏冷；")
    lines.append("  MACD＝快慢均线之差，用来判断趋势有没有转向；")
    lines.append("  成交量＝今天的活跃程度，放大说明关注度高。")
    lines.append("")
    lines.append("请按这个格式回答（给新手看的大白话）：")
    lines.append("  1) 一句话结论：偏多 / 中性 / 偏空，以及一句为什么；")
    lines.append("  2) 两到三条依据，每条把专业词翻译成日常说法；")
    lines.append("  3) 主要风险一到两条；")
    lines.append("  4) 最后一行：风险提示 + 不构成投资建议。")
    return "\n".join(lines)


def call_llm(settings, prompt, timeout=40):
    settings = settings or {}
    if not settings.get("enabled"):
        return {"ok": False, "error": "LLM 未启用（设置里勾选启用并填 key）", "text": ""}
    key = (secrets.get_key(settings) or "").strip()
    if not key:
        return {"ok": False, "error": "缺少 API key", "text": ""}
    url = (settings.get("base_url") or "").strip() or \
        "https://api.deepseek.com/chat/completions"
    model = (settings.get("model") or "").strip() or "deepseek-chat"
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
        "User-Agent": "stock-system/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - 网络/鉴权/解析错误统一上报
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc), "text": ""}
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "模型返回结构异常", "text": ""}
    return {"ok": True, "text": text, "model": model}
