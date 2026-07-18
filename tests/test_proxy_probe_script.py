from __future__ import annotations

import argparse
import unittest

from scripts.probe_proxy_fetch import parse_proxy_url, proxy_label


class ProxyProbeScriptTest(unittest.TestCase):
    def test_parse_authenticated_proxy_without_exposing_credentials_in_label(self):
        entry = parse_proxy_url(
            "http://user%40example.test:p%40ss%3Aword@proxy.example:8080"
        )

        self.assertEqual(entry["type"], "http")
        self.assertEqual(entry["host"], "proxy.example")
        self.assertEqual(entry["port"], 8080)
        self.assertEqual(entry["username"], "user@example.test")
        self.assertEqual(entry["password"], "p@ss:word")
        self.assertEqual(proxy_label(entry), "http://proxy.example:8080")

    def test_parse_socks5h_proxy(self):
        entry = parse_proxy_url("socks5h://127.0.0.1:1080")

        self.assertEqual(entry["type"], "socks5h")
        self.assertEqual(entry["host"], "127.0.0.1")
        self.assertEqual(entry["port"], 1080)
        self.assertEqual(entry["username"], "")
        self.assertEqual(entry["password"], "")

    def test_rejects_proxy_paths_and_query_parameters(self):
        for value in [
            "http://proxy.example:8080/path",
            "http://proxy.example:8080?token=secret",
        ]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parse_proxy_url(value)

    def test_rejects_invalid_port_and_partial_socks_auth(self):
        for value in [
            "http://proxy.example:0",
            "socks5://user@proxy.example:1080",
            "socks5://:password@proxy.example:1080",
        ]:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parse_proxy_url(value)


if __name__ == "__main__":
    unittest.main()
