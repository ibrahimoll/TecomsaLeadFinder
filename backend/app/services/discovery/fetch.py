"""SSRF-safe HTTP fetching for website research.

Company websites come from public map data and user edits, so every request is treated as
hostile input:
  * only http/https on ports 80/443, no credentials in URLs;
  * every host name is resolved and EVERY address must be public (no loopback, RFC 1918,
    link-local / cloud metadata 169.254.0.0/16, carrier-grade NAT, Docker networks, ULA,
    multicast, reserved...). The connection is then made to the checked address itself
    (the TLS certificate is still verified against the host name), so DNS rebinding between
    check and connect cannot reach an internal address;
  * redirects are followed manually (at most MAX_REDIRECTS) and each hop is checked again;
  * responses are streamed with a byte cap, a per-read timeout and an overall deadline
    (slow-drip servers), and only HTML/text content is read.
"""

import ipaddress
import re
import socket
import time
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

MAX_REDIRECTS = 5
ALLOWED_PORTS = {None, 80, 443}
USER_AGENT = "Mozilla/5.0 (compatible; TECOMSA-LeadFinder/1.0; company research; respects robots.txt)"
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class FetchError(Exception):
    """kind: INVALID_URL, BLOCKED_ADDRESS, DNS, CONNECT, TIMEOUT, TOO_LARGE, NOT_HTML, REDIRECTS."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def resolve(host: str) -> list[str]:
    """All addresses of a host name (replaced in tests)."""
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except (socket.gaierror, UnicodeError) as exc:
        raise FetchError("DNS", f"{host} does not resolve") from exc


_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SIX_TO_FOUR = ipaddress.ip_network("2002::/16")


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6:
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:  # NAT64 embeds an IPv4 address (64:ff9b::a9fe:a9fe = 169.254.169.254)
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        elif ip in _SIX_TO_FOUR:  # 6to4 tunnels: never needed for a company website
            return False
    return ip.is_global and not ip.is_multicast


def public_addresses(host: str) -> list[str]:
    """The host's addresses, refusing hosts that resolve to ANY non-public address."""
    host = host.strip("[]")
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
            raise FetchError("BLOCKED_ADDRESS", f"{host} is an internal host name") from None
        addresses = resolve(host)
    if not addresses:
        raise FetchError("DNS", f"{host} does not resolve")
    blocked = [a for a in addresses if not is_public(a)]
    if blocked:
        raise FetchError("BLOCKED_ADDRESS", f"{host} resolves to a non-public address ({blocked[0]})")
    return addresses


def check_url(url: str) -> str:
    """Validate scheme, port and host of a URL; returns its host. Raises FetchError."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchError("INVALID_URL", f"invalid URL: {url[:100]}") from exc
    if parts.scheme not in ("http", "https"):
        raise FetchError("INVALID_URL", f"unsupported scheme '{parts.scheme}'")
    if parts.username or parts.password:
        raise FetchError("INVALID_URL", "credentials in URLs are not allowed")
    if not parts.hostname:
        raise FetchError("INVALID_URL", "the URL has no host")
    if port not in ALLOWED_PORTS:
        raise FetchError("BLOCKED_ADDRESS", f"port {port} is not allowed (only 80 and 443)")
    public_addresses(parts.hostname)
    return parts.hostname


class _PublicOnlyBackend(httpcore.SyncBackend):
    """Connects only to a checked public address of the requested host (no rebinding window)."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        address = public_addresses(host)[0]
        return super().connect_tcp(address, port, timeout, local_address, socket_options)


class _PublicOnlyTransport(httpx.HTTPTransport):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # ponytail: httpx exposes no network_backend option; this sets httpcore's (pinned versions).
        if not hasattr(self._pool, "_network_backend"):  # fail closed if httpcore renames it
            raise RuntimeError("httpcore changed: the SSRF-safe network backend cannot be installed")
        self._pool._network_backend = _PublicOnlyBackend()


@dataclass
class Page:
    url: str  # final URL after redirects
    status: int
    content_type: str
    html: str
    redirects: list[str] = field(default_factory=list)  # URLs that redirected, in order
    truncated: bool = False  # only the first max_bytes were read (Fetcher(truncate=True))
    raw: bytes = b""  # the body itself, for documents (PDF); html is empty for those


def _decoder(content_encoding: str):
    """A zlib decompressor for gzip / deflate, None for identity. Anything else is refused: brotli/zstd
    decoders cannot bound their output, so a few KB could expand to gigabytes."""
    encoding = content_encoding.strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        return zlib.decompressobj()
    raise FetchError("NOT_HTML", f"unsupported content encoding ({encoding[:30]})")


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.IGNORECASE)


def _meta_charset(body: bytes) -> str | None:
    """The charset a page declares in its own <meta> (e.g. windows-1256 Arabic pages without an HTTP charset)."""
    found = _META_CHARSET.search(bytes(body[:4096]))
    return found[1].decode("ascii", "ignore") if found else None


DOCUMENT_TYPES = ("application/pdf", "application/vnd.ms-excel", "application/octet-stream", "application/xml",
                  "text/xml",
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                  "text/vcard", "text/x-vcard", "text/directory", "text/csv")


class Fetcher:
    """One HTTP client per research run. `transport` is replaced in tests (httpx.MockTransport)."""

    def __init__(self, *, max_bytes: int, timeout: float, transport: httpx.BaseTransport | None = None,
                 truncate: bool = False, accept_pdf: bool = False):
        """truncate: a larger page is cut at max_bytes instead of rejected (company research: the head,
        structured data and navigation come first). Memory stays bounded either way.
        accept_pdf: documents are accepted too, PDF and spreadsheets (body in Page.raw; never truncated: a cut
        document is unreadable)."""
        self.max_bytes, self.timeout, self.truncate, self.accept_pdf = max_bytes, timeout, truncate, accept_pdf
        self.client = httpx.Client(
            transport=transport or _PublicOnlyTransport(retries=0), follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 8.0)),
            # Only encodings LeadFinder decompresses itself, with a bounded output (no decompression bombs).
            headers={"User-Agent": USER_AGENT,
                     "Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.5"
                               + (",application/pdf;q=0.8,application/vnd.ms-excel;q=0.8,"
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;q=0.8"
                                  if accept_pdf else ""),
                     "Accept-Language": "en,fr;q=0.8,ar;q=0.6", "Accept-Encoding": "gzip, deflate"},
        )

    def close(self) -> None:
        self.client.close()

    def get(self, url: str) -> Page:
        """GET a page. HTTP error statuses are returned (status set), not raised."""
        redirects: list[str] = []
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url)
            deadline = time.monotonic() + self.timeout * 2  # whole response, including slow reads
            try:
                with self.client.stream("GET", url) as response:
                    if response.is_redirect and response.headers.get("location"):
                        redirects.append(url)
                        url = urljoin(url, response.headers["location"].strip())
                        continue
                    ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    pdf = self.accept_pdf and ctype in DOCUMENT_TYPES
                    if response.status_code < 400 and not ctype.startswith(_TEXT_TYPES) and not pdf:
                        raise FetchError("NOT_HTML", f"not a web page ({ctype or 'no content type'})")
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > self.max_bytes and (pdf or not self.truncate):
                        raise FetchError("TOO_LARGE", f"page larger than {self.max_bytes:,} bytes")
                    decoder = _decoder(response.headers.get("content-encoding", ""))
                    body = bytearray()
                    truncated = False
                    # Still compressed: decompressed below, bounded. (In-memory test responses are pre-read.)
                    if response.is_stream_consumed:  # already read (and decoded) in memory: nothing to bound
                        raw, decoder = iter([response.content]), None
                    else:
                        raw = response.iter_raw()
                    for chunk in raw:
                        room = self.max_bytes + 1 - len(body)
                        try:
                            body += decoder.decompress(chunk, room) if decoder else chunk
                        except zlib.error:
                            raise FetchError("NOT_HTML", "the page's compressed content is corrupt") from None
                        if len(body) > self.max_bytes or (decoder and decoder.unconsumed_tail):
                            if pdf or not self.truncate:
                                raise FetchError("TOO_LARGE", f"page larger than {self.max_bytes:,} bytes")
                            body, truncated = body[:self.max_bytes], True
                            break
                        if time.monotonic() > deadline:
                            raise FetchError("TIMEOUT", "the page took too long to download")
                    if pdf:
                        return Page(url=str(response.url), status=response.status_code, content_type=ctype,
                                    html="", redirects=redirects, raw=bytes(body))
                    encoding = response.charset_encoding or _meta_charset(body) or "utf-8"
                    try:
                        html = body.decode(encoding, errors="replace")
                    except LookupError:
                        html = body.decode("utf-8", errors="replace")
                    return Page(url=str(response.url), status=response.status_code, content_type=ctype,
                                html=html, redirects=redirects, truncated=truncated)
            except FetchError:
                raise
            except httpx.TimeoutException as exc:
                raise FetchError("TIMEOUT", "the website did not answer in time") from exc
            except httpx.TransportError as exc:
                cause = exc.__context__ or exc.__cause__
                if isinstance(cause, FetchError):  # raised by the pinned backend
                    raise cause from None
                raise FetchError("CONNECT", f"could not connect ({exc.__class__.__name__})") from exc
        raise FetchError("REDIRECTS", f"more than {MAX_REDIRECTS} redirects")
