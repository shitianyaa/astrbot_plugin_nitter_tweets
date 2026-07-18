from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import requests

import media_support.network as network_module
from media_support.network import (
    NetworkClient,
    ProxyEndpoint,
    ResponseTooLargeError,
    safe_error_for_log,
    safe_url_for_log,
)


def _entry(
    proxy_type: str = "http",
    host: str = "proxy.example",
    port: int = 8080,
    *,
    enabled: bool = True,
    username: str = "",
    password: str = "",
) -> dict:
    return {
        "__template_key": "proxy",
        "enabled": enabled,
        "type": proxy_type,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
    }


def _config(*entries: dict) -> dict:
    return {"basic": {"proxies": list(entries)}}


class _DirectResponse:
    def __init__(self, chunks: list[bytes], headers=None):
        self.chunks = list(chunks)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit=-1):
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        return chunk if limit < 0 else chunk[:limit]


class _ProxyResponse:
    def __init__(self, chunks=(), *, status=200, reason="OK", headers=None):
        self.chunks = list(chunks)
        self.status_code = status
        self.reason = reason
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        del chunk_size
        for item in self.chunks:
            if isinstance(item, BaseException):
                raise item
            yield item

    def close(self):
        self.closed = True


class _SessionFactory:
    def __init__(self, *actions):
        self.actions = list(actions)
        self.calls: list[dict] = []
        self.sessions: list[_FakeSession] = []

    def __call__(self):
        session = _FakeSession(self)
        self.sessions.append(session)
        return session


class _FakeSession:
    def __init__(self, factory: _SessionFactory):
        self.factory = factory
        self.trust_env = True
        self.closed = False

    def request(self, **kwargs):
        self.factory.calls.append({**kwargs, "trust_env": self.trust_env})
        action = self.factory.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action

    def close(self):
        self.closed = True


class ProxyEndpointTest(unittest.TestCase):
    def test_safe_url_for_log_removes_credentials_query_and_fragment(self):
        value = "https://user:secret@example.test/media/file.mp4?token=signed#part"

        self.assertEqual(
            safe_url_for_log(value),
            "https://example.test/media/file.mp4",
        )

    def test_safe_error_for_log_replaces_signed_target_url(self):
        target = "https://cdn.example.test/file.mp4?token=signed"
        error = requests.exceptions.ConnectionError(f"failed to read {target}")

        message = safe_error_for_log(error, target)

        self.assertIn("https://cdn.example.test/file.mp4", message)
        self.assertNotIn("token=", message)
        self.assertNotIn("signed", message)

    def test_supported_proxy_urls_preserve_scheme_and_order(self):
        client = NetworkClient(
            _config(
                _entry("http", port=8001),
                _entry("https", port=8002),
                _entry("socks5", port=8003),
                _entry("socks5h", port=8004),
            )
        )

        self.assertEqual(
            [endpoint.url for endpoint in client._proxies],
            [
                "http://proxy.example:8001",
                "https://proxy.example:8002",
                "socks5://proxy.example:8003",
                "socks5h://proxy.example:8004",
            ],
        )

    def test_credentials_are_encoded_and_not_exposed_by_label(self):
        endpoint = ProxyEndpoint(
            "socks5h",
            "proxy.example",
            1080,
            "alice@example.com",
            "p@ss:/word",
        )

        self.assertEqual(
            endpoint.url,
            "socks5h://alice%40example.com:p%40ss%3A%2Fword@proxy.example:1080",
        )
        self.assertEqual(endpoint.label, "socks5h://proxy.example:1080")
        self.assertNotIn("alice", repr(endpoint))
        self.assertNotIn("p@ss", repr(endpoint))

    def test_ipv6_host_is_bracketed_in_proxy_url(self):
        endpoint = ProxyEndpoint("http", "2001:db8::1", 8080)

        self.assertEqual(endpoint.url, "http://[2001:db8::1]:8080")

    def test_invalid_enabled_entries_fail_closed(self):
        client = NetworkClient(_config(_entry(host="https://bad.example")))

        with self.assertRaises(URLError) as ctx:
            client.read(Request("https://target.example"), 1, 10)

        self.assertIn("代理配置无效", str(ctx.exception.reason))

    def test_control_characters_in_host_are_rejected(self):
        client = NetworkClient(_config(_entry(host="proxy\u202e.example")))

        with self.assertRaises(URLError) as ctx:
            client.read(Request("https://target.example"), 1, 10)

        self.assertIn("代理配置无效", str(ctx.exception.reason))

    def test_invalid_proxy_inputs_are_skipped_before_valid_backup(self):
        invalid_entries = [
            _entry(host="bad%host"),
            _entry(host=r"bad\host"),
            _entry(host="bad[host"),
            _entry(host="[not-ip]"),
            _entry(username="用户", password="密码"),
            _entry("socks5", username="username-only"),
            _entry("socks5", username="u" * 128, password="password"),
        ]
        for invalid_entry in invalid_entries:
            with self.subTest(invalid_entry=invalid_entry):
                client = NetworkClient(
                    _config(
                        invalid_entry,
                        _entry("http", "backup.example", 8002),
                    )
                )
                factory = _SessionFactory(_ProxyResponse([b"backup"]))

                with patch.object(network_module.requests, "Session", factory):
                    result = client.read(
                        Request("https://target.example"),
                        2,
                        100,
                    )

                self.assertEqual(result.data, b"backup")
                self.assertEqual(len(factory.calls), 1)
                self.assertEqual(
                    factory.calls[0]["proxies"]["https"],
                    "http://backup.example:8002",
                )

    def test_disabled_entries_keep_original_direct_behavior(self):
        client = NetworkClient(_config(_entry(enabled=False)))
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, timeout))
            return _DirectResponse([b"direct"], {"X-Test": "ok"})

        with patch.object(network_module, "stdlib_urlopen", fake_urlopen):
            result = client.read(Request("https://target.example"), 3, 100)

        self.assertEqual(result.data, b"direct")
        self.assertEqual(result.headers["X-Test"], "ok")
        self.assertEqual(calls, [("https://target.example", 3)])

    def test_direct_download_rejects_incomplete_content_length(self):
        client = NetworkClient(_config())

        def fake_urlopen(request, timeout):
            del request, timeout
            return _DirectResponse([b"short"], {"Content-Length": "10"})

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "media.tmp"
            with patch.object(network_module, "stdlib_urlopen", fake_urlopen):
                with self.assertRaises(ConnectionError):
                    client.download(
                        Request("https://target.example/media"),
                        3,
                        destination,
                        100,
                    )
            self.assertFalse(destination.exists())


class ProxyFailoverTest(unittest.TestCase):
    def _client(self, *, first=None, second=None):
        return NetworkClient(
            _config(
                first or _entry("http", "first.example", 8001),
                second or _entry("http", "second.example", 8002),
            )
        )

    def test_connection_failure_switches_to_next_proxy_without_mutating_request(self):
        factory = _SessionFactory(
            requests.exceptions.ProxyError("first proxy unavailable"),
            _ProxyResponse([b"backup"], headers={"Min-Id": "42"}),
        )
        request = Request(
            "https://target.example/rss",
            data=b"payload",
            headers={"X-Test": "value"},
            method="POST",
        )
        client = self._client()

        with patch.object(network_module.requests, "Session", factory):
            result = client.read(request, 2, 100)

        self.assertEqual(result.data, b"backup")
        self.assertEqual(request.full_url, "https://target.example/rss")
        self.assertEqual(request.host, "target.example")
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(factory.calls[0]["method"], "POST")
        self.assertEqual(factory.calls[0]["data"], b"payload")
        self.assertEqual(factory.calls[0]["headers"]["X-test"], "value")
        self.assertFalse(factory.calls[0]["trust_env"])
        self.assertEqual(
            factory.calls[1]["proxies"]["https"],
            "http://second.example:8002",
        )

    def test_non_transport_request_error_does_not_switch_proxy(self):
        error = requests.exceptions.TooManyRedirects("redirect loop")
        factory = _SessionFactory(error, _ProxyResponse([b"must-not-run"]))
        client = self._client()

        with patch.object(network_module.requests, "Session", factory):
            with self.assertRaises(requests.exceptions.TooManyRedirects) as ctx:
                client.read(Request("https://target.example"), 2, 100)

        self.assertIs(ctx.exception, error)
        self.assertEqual(len(factory.calls), 1)
        self.assertTrue(factory.sessions[0].closed)

    def test_caller_proxy_authorization_header_is_not_forwarded(self):
        factory = _SessionFactory(_ProxyResponse([b"ok"]))
        client = self._client()
        request = Request(
            "https://target.example",
            headers={
                "Proxy-Authorization": "Basic stale-credential",
                "X-Test": "preserved",
            },
        )

        with patch.object(network_module.requests, "Session", factory):
            result = client.read(request, 2, 100)

        self.assertEqual(result.data, b"ok")
        sent_headers = {
            key.lower(): value for key, value in factory.calls[0]["headers"].items()
        }
        self.assertNotIn("proxy-authorization", sent_headers)
        self.assertEqual(sent_headers["x-test"], "preserved")

    def test_missing_socks_backend_can_fall_back_to_http_proxy(self):
        factory = _SessionFactory(
            requests.exceptions.InvalidSchema(
                "Missing dependencies for SOCKS support."
            ),
            _ProxyResponse([b"backup"]),
        )
        client = self._client(
            first=_entry("socks5", "first.example", 1080),
        )

        with patch.object(network_module.requests, "Session", factory):
            result = client.read(Request("https://target.example"), 2, 100)

        self.assertEqual(result.data, b"backup")
        self.assertEqual(len(factory.calls), 2)

    def test_proxy_url_encoding_error_switches_without_leaking_session(self):
        client = self._client()
        client._proxies = (
            ProxyEndpoint("http", "first.example", 8001, "\ud800", "secret"),
            client._proxies[1],
        )
        factory = _SessionFactory(_ProxyResponse([b"backup"]))

        with patch.object(network_module.requests, "Session", factory):
            result = client.read(Request("https://target.example"), 2, 100)

        self.assertEqual(result.data, b"backup")
        self.assertEqual(len(factory.sessions), 1)
        self.assertTrue(factory.sessions[0].closed)

    def test_proxy_authentication_failure_407_switches_to_next_proxy(self):
        factory = _SessionFactory(
            _ProxyResponse(status=407, reason="Proxy Authentication Required"),
            _ProxyResponse([b"ok"]),
        )
        client = self._client()

        with patch.object(network_module.requests, "Session", factory):
            result = client.read(Request("https://target.example"), 2, 100)

        self.assertEqual(result.data, b"ok")
        self.assertEqual(len(factory.calls), 2)

    def test_target_http_error_does_not_switch_proxy(self):
        username = "alice@example.com"
        password = "p@ss:/word"
        response = _ProxyResponse(
            status=404,
            reason=f"Not Found: {username} {password}",
            headers={"X-Echo": password},
        )
        factory = _SessionFactory(
            response,
            _ProxyResponse([b"must-not-run"]),
        )
        client = self._client(
            first=_entry(
                username=username,
                password=password,
            )
        )

        with patch.object(network_module.requests, "Session", factory):
            with self.assertRaises(HTTPError) as ctx:
                client.read(Request("https://target.example/missing"), 2, 100)

        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(ctx.exception.reason, "HTTP error")
        self.assertEqual(ctx.exception.headers, {})
        self.assertNotIn(username, str(ctx.exception))
        self.assertNotIn(password, str(ctx.exception))
        self.assertEqual(len(factory.calls), 1)
        self.assertTrue(response.closed)
        self.assertTrue(factory.sessions[0].closed)

    def test_body_read_failure_restarts_whole_read_on_next_proxy(self):
        factory = _SessionFactory(
            _ProxyResponse(
                [
                    b"partial",
                    requests.exceptions.ConnectionError("connection dropped"),
                ]
            ),
            _ProxyResponse([b"complete"]),
        )
        client = self._client()

        with patch.object(network_module.requests, "Session", factory):
            result = client.read(Request("https://target.example/rss"), 2, 100)

        self.assertEqual(result.data, b"complete")

    def test_zero_byte_read_does_not_consume_body_or_switch_proxy(self):
        first_response = _ProxyResponse(
            [requests.exceptions.ConnectionError("body must not be consumed")],
            headers={"X-Test": "ok"},
        )
        factory = _SessionFactory(
            first_response,
            _ProxyResponse([b"must-not-run"]),
        )
        client = self._client()

        with patch.object(network_module.requests, "Session", factory):
            result = client.read(Request("https://target.example/rss"), 2, 0)

        self.assertEqual(result.data, b"")
        self.assertEqual(result.headers["X-Test"], "ok")
        self.assertEqual(len(factory.calls), 1)
        self.assertTrue(first_response.closed)
        self.assertTrue(factory.sessions[0].closed)

    def test_download_failure_truncates_partial_file_before_next_proxy(self):
        factory = _SessionFactory(
            _ProxyResponse(
                [b"partial", requests.exceptions.ConnectionError("dropped")]
            ),
            _ProxyResponse([b"complete-file"]),
        )
        client = self._client()

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "media.tmp"
            with patch.object(network_module.requests, "Session", factory):
                client.download(
                    Request("https://target.example/media"),
                    2,
                    destination,
                    1_000,
                )
            self.assertEqual(destination.read_bytes(), b"complete-file")

    def test_incomplete_content_length_switches_to_next_proxy(self):
        factory = _SessionFactory(
            _ProxyResponse([b"short"], headers={"Content-Length": "10"}),
            _ProxyResponse([b"complete"], headers={"Content-Length": "8"}),
        )
        client = self._client()

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "media.tmp"
            with patch.object(network_module.requests, "Session", factory):
                client.download(
                    Request("https://target.example/media"),
                    2,
                    destination,
                    1_000,
                )

            self.assertEqual(destination.read_bytes(), b"complete")
        self.assertEqual(len(factory.calls), 2)

    def test_response_size_error_does_not_switch_proxy(self):
        factory = _SessionFactory(
            _ProxyResponse([b"too-large"], headers={"Content-Length": "1001"}),
            _ProxyResponse([b"must-not-run"]),
        )
        client = self._client()

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "media.tmp"
            with patch.object(network_module.requests, "Session", factory):
                with self.assertRaises(ResponseTooLargeError):
                    client.download(
                        Request("https://target.example/media"),
                        2,
                        destination,
                        1_000,
                    )
            self.assertFalse(destination.exists())
        self.assertEqual(len(factory.calls), 1)

    def test_local_file_error_does_not_switch_proxy(self):
        first_response = _ProxyResponse([b"content"])
        factory = _SessionFactory(
            first_response,
            _ProxyResponse([b"must-not-run"]),
        )
        client = self._client()

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "missing" / "media.tmp"
            with patch.object(network_module.requests, "Session", factory):
                with self.assertRaises(FileNotFoundError):
                    client.download(
                        Request("https://target.example/media"),
                        2,
                        destination,
                        1_000,
                    )

        self.assertEqual(len(factory.calls), 1)
        self.assertTrue(first_response.closed)
        self.assertTrue(factory.sessions[0].closed)

    def test_logs_and_final_error_redact_proxy_credentials(self):
        username = "alice@example.com"
        password = "p@ss:/word"
        first = _entry(
            "http",
            "first.example",
            8001,
            username=username,
            password=password,
        )
        client = self._client(first=first)
        basic_token = base64.b64encode(
            f"{username}:{password}".encode()
        ).decode("ascii")
        factory = _SessionFactory(
            requests.exceptions.ProxyError(
                "failed "
                "http://alice%40example.com:p%40ss%3A%2Fword@first.example:8001 "
                f"Proxy-Authorization: Basic {basic_token}"
            ),
            requests.exceptions.ProxyError("backup unavailable"),
        )
        warnings = []

        with (
            patch.object(network_module.requests, "Session", factory),
            patch.object(
                network_module.logger,
                "warning",
                side_effect=lambda message: warnings.append(str(message)),
            ),
        ):
            with self.assertRaises(URLError) as ctx:
                client.read(Request("https://target.example"), 2, 100)

        output = "\n".join(warnings) + "\n" + str(ctx.exception)
        self.assertNotIn(username, output)
        self.assertNotIn(password, output)
        self.assertNotIn("alice%40example.com", output)
        self.assertNotIn("p%40ss%3A%2Fword", output)
        self.assertNotIn(basic_token, output)
        self.assertIn("所有已启用代理均不可用", output)

    def test_safe_error_redacts_relative_target_query(self):
        error = RuntimeError(
            "request failed with url: /media/file.mp4?token=signed-value"
        )

        output = network_module.safe_error_for_log(
            error,
            "https://cdn.example/media/file.mp4?token=signed-value",
        )

        self.assertNotIn("signed-value", output)
        self.assertNotIn("token=", output)
        self.assertIn("/media/file.mp4", output)


if __name__ == "__main__":
    unittest.main()
