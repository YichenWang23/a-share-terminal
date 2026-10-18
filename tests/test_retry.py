# -*- coding: utf-8 -*-
"""上游重试逻辑测试：偶发失败要自动重试，重试用尽才报错。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock import datasource  # noqa: E402


class TestRetry(unittest.TestCase):
    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky(url, headers=None, timeout=12):
            calls["n"] += 1
            if calls["n"] < 3:
                raise datasource.FetchError("boom")
            return b"ok"

        with mock.patch.object(datasource, "_http_get_once", flaky):
            self.assertEqual(datasource.http_get("http://x", backoff=0), b"ok")
        self.assertEqual(calls["n"], 3)

    def test_gives_up_after_attempts(self):
        calls = {"n": 0}

        def always_fail(url, headers=None, timeout=12):
            calls["n"] += 1
            raise datasource.FetchError("down")

        with mock.patch.object(datasource, "_http_get_once", always_fail):
            with self.assertRaises(datasource.FetchError):
                datasource.http_get("http://x", attempts=2, backoff=0)
        self.assertEqual(calls["n"], 2)

    def test_default_attempts_from_env_contract(self):
        # 默认至少重试 1 次以上（不允许「一次失败就放弃」）
        self.assertGreaterEqual(datasource.FETCH_ATTEMPTS, 2)




class TestRetryPolicy(unittest.TestCase):
    def test_permanent_error_is_not_retried(self):
        """501/403/429 这类确定性失败不该重试：重试只是白等退避。"""
        calls = {"n": 0}

        def fail_501(url, headers=None, timeout=12):
            calls["n"] += 1
            raise datasource.FetchError("HTTPError: 501", status=501)

        with mock.patch.object(datasource, "_http_get_once", fail_501):
            with self.assertRaises(datasource.FetchError):
                datasource.http_get("http://x", backoff=0)
        self.assertEqual(calls["n"], 1, "501 只该请求一次，实际 %d 次" % calls["n"])

    def test_transient_error_is_retried(self):
        """普通网络异常（无状态码）仍然重试。"""
        calls = {"n": 0}

        def flaky(url, headers=None, timeout=12):
            calls["n"] += 1
            if calls["n"] < 2:
                raise datasource.FetchError("timeout")
            return b"ok"

        with mock.patch.object(datasource, "_http_get_once", flaky):
            self.assertEqual(datasource.http_get("http://x", backoff=0), b"ok")
        self.assertEqual(calls["n"], 2)

    def test_circuit_breaker_marks_and_expires(self):
        datasource._SOURCE_DOWN_UNTIL.clear()
        self.assertFalse(datasource.source_down("test-src"))
        datasource.mark_source_down("test-src", cooldown=0.05)
        self.assertTrue(datasource.source_down("test-src"), "刚熔断时应跳过该源")
        import time as _t
        _t.sleep(0.08)
        self.assertFalse(datasource.source_down("test-src"), "冷却过后应恢复")
        datasource._SOURCE_DOWN_UNTIL.clear()


if __name__ == "__main__":
    unittest.main()
