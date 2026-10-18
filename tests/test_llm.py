# -*- coding: utf-8 -*-
"""真模型通道测试：用桩替换 HTTP，不联网、不需要真 key。

覆盖：未启用/缺 key 的拒绝、请求体与鉴权头、成功解析、结构异常、网络异常，
以及「模型失败要回落规则引擎并带上原因」这条降级契约。
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import llm  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def reply(text="模型结论：中性"):
    return FakeResponse(json.dumps({
        "choices": [{"message": {"content": text}}],
    }).encode("utf-8"))


SETTINGS = {"enabled": True, "api_key_enc": "stub", "model": "deepseek-chat",
            "base_url": "https://example.invalid/chat/completions"}


class TestPrompt(unittest.TestCase):
    def test_prompt_contains_quote_and_metrics(self):
        prompt = llm.build_prompt({
            "name": "贵州茅台", "code": "600519", "price": 1329.0,
            "metrics": {"ma20": 1300.1, "rsi14": 55.2},
            "rule_engine": {"bullets": ["均线多头"]},
            "position": {"shares": 100, "avg_cost": 1300.0},
        })
        for token in ("贵州茅台", "600519", "1329.0", "ma20", "rsi14",
                      "均线多头", "100", "风险"):
            self.assertIn(token, prompt, "提示词缺少 %s" % token)

    def test_prompt_has_no_position_block_when_flat(self):
        prompt = llm.build_prompt({"name": "A", "code": "000001"})
        self.assertNotIn("我的持仓", prompt)


class TestPlainLanguage(unittest.TestCase):
    def test_system_prompt_is_plain_language(self):
        prompt = llm.SYSTEM_PROMPT
        for kw in ("大白话", "新手", "翻译成人话", "不构成投资建议"):
            self.assertIn(kw, prompt, "系统提示词缺少通俗化要求：%s" % kw)
        self.assertIn("不要给", prompt, "要明确禁止操作指令")

    def test_build_prompt_has_glossary_and_plain_format(self):
        prompt = llm.build_prompt({"name": "平安银行", "code": "000001", "price": 11.5,
                                   "metrics": {"rsi14": 72.0}})
        for kw in ("术语对照", "RSI", "MA5", "MACD", "一句话结论", "不构成投资建议"):
            self.assertIn(kw, prompt, "用户提示词缺少：%s" % kw)


class TestCallLLM(unittest.TestCase):
    def test_disabled_returns_error(self):
        res = llm.call_llm({"enabled": False}, "p")
        self.assertFalse(res["ok"])
        self.assertIn("未启用", res["error"])

    def test_missing_key_returns_error(self):
        with mock.patch.object(llm.secrets, "get_key", return_value=""):
            res = llm.call_llm(SETTINGS, "p")
        self.assertFalse(res["ok"])
        self.assertIn("缺少 API key", res["error"])

    def test_success_parses_content_and_sends_auth(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return reply("偏多：均线多头排列")

        with mock.patch.object(llm.secrets, "get_key", return_value="sk-test-123"), \
                mock.patch.object(llm.urllib.request, "urlopen", fake_urlopen):
            res = llm.call_llm(SETTINGS, "请看这只票")

        self.assertTrue(res["ok"], res)
        self.assertEqual(res["text"], "偏多：均线多头排列")
        self.assertEqual(res["model"], "deepseek-chat")
        self.assertEqual(captured["headers"]["authorization"], "Bearer sk-test-123")
        self.assertEqual(captured["body"]["model"], "deepseek-chat")
        self.assertEqual(captured["body"]["messages"][0]["role"], "system")
        self.assertEqual(captured["body"]["messages"][1]["content"], "请看这只票")
        self.assertFalse(captured["body"]["stream"])

    def test_network_error_is_reported_not_raised(self):
        def boom(req, timeout=None):
            raise OSError("connection refused")

        with mock.patch.object(llm.secrets, "get_key", return_value="sk-x"), \
                mock.patch.object(llm.urllib.request, "urlopen", boom):
            res = llm.call_llm(SETTINGS, "p")
        self.assertFalse(res["ok"])
        self.assertIn("connection refused", res["error"])

    def test_malformed_payload_is_reported(self):
        with mock.patch.object(llm.secrets, "get_key", return_value="sk-x"), \
                mock.patch.object(llm.urllib.request, "urlopen",
                                  lambda req, timeout=None:
                                  FakeResponse(b'{"foo": 1}')):
            res = llm.call_llm(SETTINGS, "p")
        self.assertFalse(res["ok"])
        self.assertIn("结构异常", res["error"])

    def test_uses_default_url_and_model_when_blank(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return reply()

        with mock.patch.object(llm.secrets, "get_key", return_value="sk-x"), \
                mock.patch.object(llm.urllib.request, "urlopen", fake_urlopen):
            llm.call_llm({"enabled": True, "base_url": "", "model": ""}, "p")
        self.assertEqual(seen["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(seen["body"]["model"], "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
