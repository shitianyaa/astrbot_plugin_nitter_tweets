from __future__ import annotations

import base64
import http.client
import ipaddress
import select
import socket
import socketserver
import struct
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request

from media_support.network import NetworkClient


def _proxy_entry(
    proxy_type: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
) -> dict:
    return {
        "__template_key": "proxy",
        "enabled": True,
        "type": proxy_type,
        "host": "127.0.0.1",
        "port": port,
        "username": username,
        "password": password,
    }


def _config(*entries: dict) -> dict:
    return {"basic": {"proxies": list(entries)}}


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        del format, args


class _TargetHandler(_QuietHandler):
    def do_GET(self):
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.server.requests.append((self.path, headers))
        body = f"target:{self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Target", "local")
        self.end_headers()
        self.wfile.write(body)


class _HttpProxyHandler(_QuietHandler):
    def do_GET(self):
        proxy_auth = self.headers.get("Proxy-Authorization", "")
        self.server.requests.append((self.path, proxy_auth))
        expected_auth = self.server.expected_auth
        if expected_auth and proxy_auth != expected_auth:
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="test"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        parsed = urlsplit(self.path)
        if parsed.scheme != "http" or not parsed.hostname:
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        upstream = http.client.HTTPConnection(
            parsed.hostname,
            parsed.port or 80,
            timeout=2,
        )
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {
                "connection",
                "host",
                "proxy-authorization",
                "proxy-connection",
            }
        }
        headers["Host"] = parsed.netloc
        try:
            upstream.request("GET", path, headers=headers)
            response = upstream.getresponse()
            body = response.read()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in {
                    "connection",
                    "content-length",
                    "proxy-authenticate",
                    "transfer-encoding",
                }:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            upstream.close()


class _DropConnectionHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.connection_count += 1
        self.request.recv(4096)


class _TlsProbeHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            handshake = _recv_exact(self.request, 5)
        except ConnectionError:
            return
        self.server.handshakes.append(handshake)


class _ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("unexpected EOF")
        data.extend(chunk)
    return bytes(data)


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    while sockets:
        readable, _, _ = select.select(sockets, [], [], 3)
        if not readable:
            return
        for source in readable:
            data = source.recv(64 * 1024)
            if not data:
                return
            destination = right if source is left else left
            destination.sendall(data)


class _Socks5Handler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        version, method_count = _recv_exact(client, 2)
        if version != 5:
            return
        methods = _recv_exact(client, method_count)
        expected_auth = getattr(self.server, "expected_auth", None)
        auth_method = 2 if expected_auth else 0
        if auth_method not in methods:
            client.sendall(b"\x05\xff")
            return
        client.sendall(bytes((5, auth_method)))

        if auth_method == 2:
            auth_version, username_length = _recv_exact(client, 2)
            username = _recv_exact(client, username_length).decode("utf-8")
            password_length = _recv_exact(client, 1)[0]
            password = _recv_exact(client, password_length).decode("utf-8")
            self.server.auth_attempts.append((username, password))
            if auth_version != 1 or (username, password) != expected_auth:
                client.sendall(b"\x01\x01")
                return
            client.sendall(b"\x01\x00")

        version, command, reserved, address_type = _recv_exact(client, 4)
        if (version, command, reserved) != (5, 1, 0):
            return
        if address_type == 1:
            raw_host = _recv_exact(client, 4)
            host = socket.inet_ntop(socket.AF_INET, raw_host)
        elif address_type == 3:
            length = _recv_exact(client, 1)[0]
            host = _recv_exact(client, length).decode("ascii")
        elif address_type == 4:
            raw_host = _recv_exact(client, 16)
            host = socket.inet_ntop(socket.AF_INET6, raw_host)
        else:
            return
        port = struct.unpack("!H", _recv_exact(client, 2))[0]
        self.server.requests.append((address_type, host, port))

        try:
            parsed_host = ipaddress.ip_address(host)
        except ValueError:
            upstream_host = "127.0.0.1" if host == "localhost" else host
        else:
            upstream_host = "127.0.0.1" if parsed_host.is_loopback else host

        try:
            upstream = socket.create_connection((upstream_host, port), timeout=2)
        except OSError:
            client.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            return

        with upstream:
            bound_host, bound_port = upstream.getsockname()[:2]
            client.sendall(
                b"\x05\x00\x00\x01"
                + socket.inet_aton(bound_host)
                + struct.pack("!H", bound_port)
            )
            _relay(client, upstream)


@contextmanager
def _running_server(server):
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _target_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TargetHandler)
    server.requests = []
    return server


def _http_proxy_server(*, expected_auth: str = "") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HttpProxyHandler)
    server.requests = []
    server.expected_auth = expected_auth
    return server


def _socks5_server(*, expected_auth=None) -> _ThreadingTcpServer:
    server = _ThreadingTcpServer(("127.0.0.1", 0), _Socks5Handler)
    server.requests = []
    server.expected_auth = expected_auth
    server.auth_attempts = []
    return server


class ProxyIntegrationTest(unittest.TestCase):
    def test_http_proxy_reaches_local_http_target(self):
        with (
            _running_server(_target_server()) as target,
            _running_server(_http_proxy_server()) as proxy,
        ):
            target_url = f"http://127.0.0.1:{target.server_port}/through-proxy"
            client = NetworkClient(_config(_proxy_entry("http", proxy.server_port)))

            result = client.read(Request(target_url), timeout=2, max_bytes=1024)

        self.assertEqual(result.data, b"target:/through-proxy")
        self.assertEqual(result.headers["X-Target"], "local")
        self.assertEqual(len(proxy.requests), 1)
        self.assertEqual(target.requests[0][0], "/through-proxy")

    def test_real_proxy_disconnect_fails_over_to_second_proxy(self):
        broken = _ThreadingTcpServer(("127.0.0.1", 0), _DropConnectionHandler)
        broken.connection_count = 0
        with (
            _running_server(_target_server()) as target,
            _running_server(broken),
            _running_server(_http_proxy_server()) as backup,
        ):
            target_url = f"http://127.0.0.1:{target.server_port}/after-failover"
            client = NetworkClient(
                _config(
                    _proxy_entry("http", broken.server_address[1]),
                    _proxy_entry("http", backup.server_port),
                )
            )

            result = client.read(Request(target_url), timeout=2, max_bytes=1024)

        self.assertGreaterEqual(broken.connection_count, 1)
        self.assertEqual(len(backup.requests), 1)
        self.assertEqual(result.data, b"target:/after-failover")

    def test_https_proxy_starts_tls_and_tls_failure_fails_over(self):
        tls_probe = _ThreadingTcpServer(("127.0.0.1", 0), _TlsProbeHandler)
        tls_probe.handshakes = []
        with (
            _running_server(_target_server()) as target,
            _running_server(tls_probe),
            _running_server(_http_proxy_server()) as backup,
        ):
            target_url = f"http://127.0.0.1:{target.server_port}/https-proxy"
            client = NetworkClient(
                _config(
                    _proxy_entry("https", tls_probe.server_address[1]),
                    _proxy_entry("http", backup.server_port),
                )
            )

            result = client.read(Request(target_url), timeout=2, max_bytes=1024)

        self.assertEqual(result.data, b"target:/https-proxy")
        self.assertEqual(len(tls_probe.handshakes), 1)
        self.assertEqual(tls_probe.handshakes[0][0], 0x16)
        self.assertEqual(tls_probe.handshakes[0][1], 0x03)
        self.assertEqual(len(backup.requests), 1)

    def test_basic_proxy_auth_succeeds_without_leaking_to_target(self):
        username = "alice@example.com"
        password = "p@ss:/word"
        expected_auth = "Basic " + base64.b64encode(
            f"{username}:{password}".encode()
        ).decode("ascii")
        with (
            _running_server(_target_server()) as target,
            _running_server(
                _http_proxy_server(expected_auth=expected_auth)
            ) as proxy,
        ):
            target_url = f"http://127.0.0.1:{target.server_port}/authenticated"
            request = Request(target_url, headers={"X-Caller": "integration"})
            client = NetworkClient(
                _config(
                    _proxy_entry(
                        "http",
                        proxy.server_port,
                        username=username,
                        password=password,
                    )
                )
            )

            result = client.read(request, timeout=2, max_bytes=1024)

        self.assertEqual(result.data, b"target:/authenticated")
        self.assertEqual(proxy.requests[0][1], expected_auth)
        target_headers = target.requests[0][1]
        self.assertEqual(target_headers["x-caller"], "integration")
        self.assertNotIn("proxy-authorization", target_headers)
        self.assertNotIn(username, repr(target_headers))
        self.assertNotIn(password, repr(target_headers))

    def test_socks5_and_socks5h_use_local_and_proxy_dns_respectively(self):
        socks = _socks5_server()
        with (
            _running_server(_target_server()) as target,
            _running_server(socks),
        ):
            for scheme in ("socks5", "socks5h"):
                with self.subTest(scheme=scheme):
                    target_url = f"http://localhost:{target.server_port}/{scheme}"
                    client = NetworkClient(
                        _config(
                            _proxy_entry(scheme, socks.server_address[1])
                        )
                    )
                    result = client.read(
                        Request(target_url),
                        timeout=2,
                        max_bytes=1024,
                    )
                    self.assertEqual(result.data, f"target:/{scheme}".encode())

        self.assertEqual(len(socks.requests), 2)
        local_dns_type, local_dns_host, _ = socks.requests[0]
        proxy_dns_type, proxy_dns_host, _ = socks.requests[1]
        self.assertIn(local_dns_type, {1, 4})
        self.assertNotEqual(local_dns_host, "localhost")
        self.assertEqual(proxy_dns_type, 3)
        self.assertEqual(proxy_dns_host, "localhost")

    def test_socks5_username_password_authentication(self):
        username = "用户@example.com"
        password = "密码:/word"
        socks = _socks5_server(expected_auth=(username, password))
        with (
            _running_server(_target_server()) as target,
            _running_server(socks),
        ):
            target_url = f"http://localhost:{target.server_port}/socks-auth"
            client = NetworkClient(
                _config(
                    _proxy_entry(
                        "socks5h",
                        socks.server_address[1],
                        username=username,
                        password=password,
                    )
                )
            )

            result = client.read(Request(target_url), timeout=2, max_bytes=1024)

        self.assertEqual(result.data, b"target:/socks-auth")
        self.assertEqual(socks.auth_attempts, [(username, password)])
        target_headers = target.requests[0][1]
        self.assertNotIn("proxy-authorization", target_headers)
        self.assertNotIn(username, repr(target_headers))
        self.assertNotIn(password, repr(target_headers))


if __name__ == "__main__":
    unittest.main()
