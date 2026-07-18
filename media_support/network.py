from __future__ import annotations

import base64
import unicodedata
from dataclasses import dataclass, field
from ipaddress import IPv6Address, ip_address
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen as stdlib_urlopen

try:
    import requests
except ImportError:  # pragma: no cover - handled when a proxy is enabled
    requests = None

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover - tests without astrbot
    class _FallbackLogger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    logger = _FallbackLogger()

try:
    from ..config import config_get
except ImportError:
    from config import config_get


SUPPORTED_PROXY_TYPES = frozenset({"http", "https", "socks5", "socks5h"})
_READ_CHUNK_SIZE = 64 * 1024
_DOWNLOAD_CHUNK_SIZE = 256 * 1024


class ResponseTooLargeError(RuntimeError):
    """Raised when a streamed response exceeds the configured byte limit."""


class ResponseIncompleteError(ConnectionError):
    """Raised when a streamed response ends before its declared length."""


class _ProxyAttemptError(RuntimeError):
    """A safe, retryable proxy error whose text contains no credentials."""


@dataclass(frozen=True, slots=True)
class ProxyEndpoint:
    proxy_type: str
    host: str
    port: int
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)

    @property
    def label(self) -> str:
        return f"{self.proxy_type}://{_url_host(self.host)}:{self.port}"

    @property
    def url(self) -> str:
        if self.username or self.password:
            username = quote(self.username, safe="")
            password = quote(self.password, safe="")
            auth = f"{username}:{password}@"
        else:
            auth = ""
        return f"{self.proxy_type}://{auth}{_url_host(self.host)}:{self.port}"


@dataclass(frozen=True, slots=True)
class NetworkReadResult:
    data: bytes
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class _ProxyConfig:
    endpoints: tuple[ProxyEndpoint, ...]
    invalid_enabled_entries: int = 0


class NetworkClient:
    """Synchronous HTTP client with ordered proxy failover.

    Existing callers already run network work in worker threads. A fresh
    requests Session is used for each proxy attempt so concurrent scheduler
    jobs never share mutable session or proxy-auth state.
    """

    def __init__(self, config):
        parsed = _load_proxy_config(config)
        self._proxies = parsed.endpoints
        self._invalid_enabled_entries = parsed.invalid_enabled_entries
        if self._proxies:
            logger.info(
                "[NitterTweets] 已启用代理故障切换: "
                f"count={len(self._proxies)}"
            )

    @property
    def proxy_count(self) -> int:
        return len(self._proxies)

    def read(self, request: Request, timeout: float, max_bytes: int) -> NetworkReadResult:
        """Read at most ``max_bytes`` and retry the whole read on the next proxy."""
        if not self._proxies:
            self._ensure_direct_allowed()
            return self._read_direct(request, timeout, max_bytes)

        return self._run_with_failover(
            lambda endpoint: self._read_via_proxy(
                endpoint, request, timeout, max_bytes
            )
        )

    def download(
        self,
        request: Request,
        timeout: float,
        destination: Path,
        max_bytes: int,
    ) -> dict[str, str]:
        """Download atomically per attempt, truncating partial proxy results."""
        destination = Path(destination)
        try:
            if not self._proxies:
                self._ensure_direct_allowed()
                return self._download_direct(
                    request, timeout, destination, max_bytes
                )

            return self._run_with_failover(
                lambda endpoint: self._download_via_proxy(
                    endpoint, request, timeout, destination, max_bytes
                )
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def _ensure_direct_allowed(self) -> None:
        if self._invalid_enabled_entries:
            raise URLError("代理配置无效：没有可用的已启用代理")

    @staticmethod
    def _read_direct(
        request: Request, timeout: float, max_bytes: int
    ) -> NetworkReadResult:
        with stdlib_urlopen(request, timeout=timeout) as response:
            return NetworkReadResult(
                data=response.read(max(0, int(max_bytes))),
                headers=_copy_headers(getattr(response, "headers", {})),
            )

    @staticmethod
    def _download_direct(
        request: Request,
        timeout: float,
        destination: Path,
        max_bytes: int,
    ) -> dict[str, str]:
        with stdlib_urlopen(request, timeout=timeout) as response:
            headers = _copy_headers(response.headers)
            _check_content_length(headers, max_bytes)
            downloaded = _write_stdlib_response(response, destination, max_bytes)
            _check_complete_length(headers, downloaded)
            return headers

    def _read_via_proxy(
        self,
        endpoint: ProxyEndpoint,
        request: Request,
        timeout: float,
        max_bytes: int,
    ) -> NetworkReadResult:
        session, response = self._open_proxy_response(endpoint, request, timeout)
        try:
            data = bytearray()
            limit = max(0, int(max_bytes))
            if limit == 0:
                return NetworkReadResult(b"", _copy_headers(response.headers))
            for chunk in response.iter_content(chunk_size=_READ_CHUNK_SIZE):
                if not chunk:
                    continue
                data.extend(chunk[: limit - len(data)])
                if len(data) >= limit:
                    break
            return NetworkReadResult(bytes(data), _copy_headers(response.headers))
        except Exception as exc:
            self._raise_proxy_transport_error(endpoint, exc, request.full_url)
            raise  # pragma: no cover - helper always raises
        finally:
            response.close()
            session.close()

    def _download_via_proxy(
        self,
        endpoint: ProxyEndpoint,
        request: Request,
        timeout: float,
        destination: Path,
        max_bytes: int,
    ) -> dict[str, str]:
        session, response = self._open_proxy_response(endpoint, request, timeout)
        try:
            headers = _copy_headers(response.headers)
            _check_content_length(headers, max_bytes)
            downloaded = 0
            with destination.open("wb") as file:
                for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise ResponseTooLargeError(
                            f"response exceeds {max_bytes} bytes"
                        )
                    file.write(chunk)
            _check_complete_length(headers, downloaded)
            return headers
        except ResponseTooLargeError:
            raise
        except Exception as exc:
            self._raise_proxy_transport_error(endpoint, exc, request.full_url)
            raise  # pragma: no cover - helper always raises
        finally:
            response.close()
            session.close()

    @staticmethod
    def _open_proxy_response(
        endpoint: ProxyEndpoint,
        request: Request,
        timeout: float,
    ):
        if requests is None:
            raise _ProxyAttemptError("缺少 requests[socks] 运行依赖")

        try:
            proxy_url = endpoint.url
        except (UnicodeError, ValueError):
            raise _ProxyAttemptError("代理地址或凭据编码无效") from None

        session = requests.Session()
        session.trust_env = False
        try:
            response = session.request(
                method=request.get_method(),
                url=request.full_url,
                headers={
                    key: value
                    for key, value in request.header_items()
                    if key.lower() != "proxy-authorization"
                },
                data=request.data,
                timeout=timeout,
                proxies={"http": proxy_url, "https": proxy_url},
                stream=True,
                allow_redirects=True,
            )
        except Exception as exc:
            session.close()
            NetworkClient._raise_proxy_transport_error(
                endpoint, exc, request.full_url
            )
            raise  # pragma: no cover - helper always raises

        if response.status_code == 407:
            response.close()
            session.close()
            raise _ProxyAttemptError("HTTP 407 代理认证失败")
        if response.status_code >= 400:
            error = HTTPError(
                request.full_url,
                response.status_code,
                "HTTP error",
                {},
                None,
            )
            response.close()
            session.close()
            raise error
        return session, response

    @staticmethod
    def _raise_proxy_transport_error(
        endpoint: ProxyEndpoint,
        exc: BaseException,
        target_url: str = "",
    ) -> None:
        if isinstance(exc, (HTTPError, ResponseTooLargeError, _ProxyAttemptError)):
            raise exc
        if isinstance(exc, ResponseIncompleteError):
            message = _redact_error(exc, endpoint, target_url)
            raise _ProxyAttemptError(message) from None
        if requests is not None and isinstance(
            exc, requests.exceptions.RequestException
        ) and _is_retryable_requests_error(endpoint, exc):
            message = _redact_error(exc, endpoint, target_url)
            raise _ProxyAttemptError(message) from None
        raise exc

    def _run_with_failover(self, operation):
        last_error: _ProxyAttemptError | None = None
        for index, endpoint in enumerate(self._proxies):
            try:
                return operation(endpoint)
            except _ProxyAttemptError as exc:
                last_error = exc
                remaining = len(self._proxies) - index - 1
                logger.warning(
                    "[NitterTweets] 代理请求失败"
                    + ("，切换下一条" if remaining else "，已无可用代理")
                    + f": proxy={endpoint.label}, remaining={remaining}, error={exc}"
                )

        if last_error is None:  # pragma: no cover - guarded by caller
            raise URLError("没有可用的已启用代理")
        raise URLError("所有已启用代理均不可用") from last_error


def _is_retryable_requests_error(
    endpoint: ProxyEndpoint,
    exc: BaseException,
) -> bool:
    if requests is None:  # pragma: no cover - guarded by caller
        return False
    errors = requests.exceptions
    if isinstance(
        exc,
        (
            errors.ConnectionError,
            errors.Timeout,
            errors.ChunkedEncodingError,
            errors.ContentDecodingError,
            errors.RetryError,
        ),
    ):
        return True
    return (
        endpoint.proxy_type in {"socks5", "socks5h"}
        and isinstance(exc, errors.InvalidSchema)
        and "socks support" in str(exc).lower()
    )


def _load_proxy_config(config) -> _ProxyConfig:
    raw = config_get(config, "proxies", []) or []
    if not isinstance(raw, list):
        logger.warning("[NitterTweets] 忽略无效代理列表：配置值不是列表")
        return _ProxyConfig((), 1)

    endpoints: list[ProxyEndpoint] = []
    invalid_enabled_entries = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not bool(item.get("enabled", False)):
            continue
        endpoint = _parse_proxy_entry(item)
        if endpoint is None:
            invalid_enabled_entries += 1
            logger.warning(
                f"[NitterTweets] 忽略无效的已启用代理: index={index}"
            )
            continue
        endpoints.append(endpoint)
    return _ProxyConfig(tuple(endpoints), invalid_enabled_entries)


def _parse_proxy_entry(item: dict) -> ProxyEndpoint | None:
    proxy_type = str(item.get("type") or "http").strip().lower()
    if proxy_type not in SUPPORTED_PROXY_TYPES:
        return None

    host = _normalize_host(item.get("host"))
    if not host:
        return None

    try:
        port = int(item.get("port"))
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None

    username = str(item.get("username") or "")
    password = str(item.get("password") or "")
    if not _proxy_credentials_supported(proxy_type, username, password):
        return None

    return ProxyEndpoint(
        proxy_type=proxy_type,
        host=host,
        port=port,
        username=username,
        password=password,
    )


def _proxy_credentials_supported(
    proxy_type: str,
    username: str,
    password: str,
) -> bool:
    if proxy_type in {"http", "https"}:
        try:
            username.encode("latin-1")
            password.encode("latin-1")
        except UnicodeEncodeError:
            return False
        return True

    if bool(username) != bool(password):
        return False
    try:
        encoded_username = username.encode("utf-8")
        encoded_password = password.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return len(encoded_username) <= 127 and len(encoded_password) <= 127


def _normalize_host(value) -> str:
    host = str(value or "").strip()
    if not host or "://" in host or any(char in host for char in "/?#@%\\"):
        return ""
    if any(
        char.isspace() or unicodedata.category(char).startswith("C")
        for char in host
    ):
        return ""

    has_bracket = host.startswith("[") or host.endswith("]")
    if has_bracket:
        if not (host.startswith("[") and host.endswith("]")):
            return ""
        candidate = host[1:-1]
        try:
            parsed = ip_address(candidate)
        except ValueError:
            return ""
        return str(parsed) if isinstance(parsed, IPv6Address) else ""
    if "[" in host or "]" in host:
        return ""

    try:
        return str(ip_address(host))
    except ValueError:
        pass
    if ":" in host:
        return ""

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    normalized = ascii_host[:-1] if ascii_host.endswith(".") else ascii_host
    if not normalized or len(normalized) > 253:
        return ""
    labels = normalized.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or any(
            not char.isascii()
            or not (char.isalnum() or char in {"-", "_"})
            for char in label
        )
        for label in labels
    ):
        return ""
    return ascii_host


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _copy_headers(headers) -> dict[str, str]:
    try:
        return {str(key): str(value) for key, value in headers.items()}
    except AttributeError:
        return {}


def _check_content_length(headers: dict[str, str], max_bytes: int) -> None:
    raw_length = next(
        (value for key, value in headers.items() if key.lower() == "content-length"),
        "",
    )
    try:
        content_length = int(raw_length)
    except (TypeError, ValueError):
        return
    if content_length > max_bytes:
        raise ResponseTooLargeError(f"response exceeds {max_bytes} bytes")


def _write_stdlib_response(response, destination: Path, max_bytes: int) -> int:
    downloaded = 0
    with destination.open("wb") as file:
        while True:
            chunk = response.read(_DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            downloaded += len(chunk)
            if downloaded > max_bytes:
                raise ResponseTooLargeError(f"response exceeds {max_bytes} bytes")
            file.write(chunk)
    return downloaded


def _check_complete_length(headers: dict[str, str], downloaded: int) -> None:
    raw_length = next(
        (value for key, value in headers.items() if key.lower() == "content-length"),
        "",
    )
    try:
        expected = int(raw_length)
    except (TypeError, ValueError):
        return
    if expected >= 0 and downloaded != expected:
        raise ResponseIncompleteError(
            f"incomplete response: expected {expected} bytes, got {downloaded}"
        )


def safe_url_for_log(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text.split("?", 1)[0].split("#", 1)[0]
    if not parsed.scheme or not parsed.netloc:
        return text.split("?", 1)[0].split("#", 1)[0]

    try:
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return "<invalid-url>"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host + (f":{port}" if port is not None else "")
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def safe_error_for_log(exc: BaseException, target_url: str = "") -> str:
    text = str(exc) or type(exc).__name__
    if target_url:
        safe_url = safe_url_for_log(target_url)
        text = text.replace(target_url, safe_url)
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.path:
            relative_target = parsed.path
            if parsed.query:
                relative_target += f"?{parsed.query}"
            if parsed.fragment:
                relative_target += f"#{parsed.fragment}"
            text = text.replace(relative_target, parsed.path)
    return " ".join(text.split())[:300]


def _redact_error(
    exc: BaseException,
    endpoint: ProxyEndpoint,
    target_url: str = "",
) -> str:
    text = safe_error_for_log(exc, target_url)
    secrets = {
        endpoint.username,
        endpoint.password,
        quote(endpoint.username, safe=""),
        quote(endpoint.password, safe=""),
        endpoint.url,
    }
    if endpoint.username or endpoint.password:
        basic_token = base64.b64encode(
            f"{endpoint.username}:{endpoint.password}".encode("utf-8")
        ).decode("ascii")
        secrets.update({basic_token, f"Basic {basic_token}"})
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "***")
    text = " ".join(text.split())
    return f"{type(exc).__name__}: {text[:300]}"
