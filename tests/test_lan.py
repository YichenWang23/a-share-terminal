# -*- coding: utf-8 -*-
"""局域网地址探测的测试。"""
import unittest

import server


class TestLanAddresses(unittest.TestCase):
    def test_shape(self):
        addrs = server.lan_addresses()
        self.assertIsInstance(addrs, list)
        self.assertEqual(len(addrs), len(set(addrs)), "不应有重复地址")

    def test_no_loopback_or_link_local(self):
        for ip in server.lan_addresses():
            self.assertFalse(ip.startswith("127."), "不应出现本机回环：%s" % ip)
            self.assertFalse(ip.startswith("169.254."), "不应出现链路本地：%s" % ip)

    def test_primary_first(self):
        addrs = server.lan_addresses()
        if not addrs:
            self.skipTest("这台机器没有局域网地址")
        # 主地址应该是可用的 IPv4
        self.assertEqual(len(addrs[0].split(".")), 4)


if __name__ == "__main__":
    unittest.main()
