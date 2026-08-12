"""Small synchronous RDAP client used by Guardian's domain registration logic.

The client deliberately keeps HTTP and persistence behind protocols.  This makes
the security-sensitive URL selection testable without network access and lets the
SQLite cache own all persistence concerns.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import idna

from guardian_classic.domain_cache import BootstrapCacheEntry


IANA_DNS_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BOOTSTRAP_FRESHNESS_SECONDS = 24 * 60 * 60
BOOTSTRAP_STALE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
BOOTSTRAP_FAILURE_BACKOFF_SECONDS = 5 * 60
BOOTSTRAP_MAX_BYTES = 2 * 1024 * 1024
RDAP_MAX_BYTES = 1 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 5.0
DEFAULT_ENDPOINT_BACKOFF_SECONDS = 2 * 60
MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60

_RDAP_SOURCE = "rdap"
_USER_AGENT = "GuardianClassic/0.1 RDAP client"


@dataclass(frozen=True, slots=True)
class RdapLookupResult:
    status: str
    registered_at: datetime | None
    source: str | None
    error_code: str | None = None
    retry_after: int | None = None


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class ResponseTooLargeError(Exception):
    """Raised before an oversized HTTP response is handed to a parser."""


class RdapTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> TransportResponse: ...


class BootstrapCache(Protocol):
    def get_bootstrap(self) -> BootstrapCacheEntry | None: ...

    def put_bootstrap(
        self,
        payload: str,
        fetched_at: int,
        fresh_until: int,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None: ...

    def get_endpoint_backoff(self, endpoint: str) -> int | None: ...

    def put_endpoint_backoff(
        self,
        endpoint: str,
        retry_after: int,
        observed_at: int,
    ) -> None: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    """Stdlib transport which returns HTTP errors and never follows redirects."""

    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> TransportResponse:
        request = Request(url, headers=dict(headers), method="GET")

        try:
            with self._opener.open(request, timeout=timeout) as response:
                return TransportResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=_read_limited(response, max_bytes),
                )
        except HTTPError as error:
            try:
                body = _read_limited(error, max_bytes)
            finally:
                error.close()

            return TransportResponse(
                status=error.code,
                headers=dict(error.headers.items()),
                body=body,
            )


@dataclass(frozen=True, slots=True)
class _BootstrapData:
    services: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    stale: bool = False


class _ClientFailure(Exception):
    def __init__(
        self,
        status: str,
        error_code: str,
        *,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(error_code)
        self.status = status
        self.error_code = error_code
        self.retry_after = retry_after


class RdapClient:
    def __init__(
        self,
        cache: BootstrapCache,
        *,
        transport: RdapTransport | None = None,
        clock: Callable[[], datetime | int | float] | None = None,
    ) -> None:
        self._cache = cache
        self._transport = transport or UrllibTransport()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._bootstrap_lock = threading.Lock()

    def lookup(self, domain: str) -> RdapLookupResult:
        ascii_domain = _normalize_domain(domain)
        if ascii_domain is None:
            return RdapLookupResult(
                status="parse_error",
                registered_at=None,
                source=None,
                error_code="invalid_domain",
            )

        now = _epoch_seconds(self._clock())

        try:
            bootstrap = self._load_bootstrap(now)
        except _ClientFailure as error:
            return RdapLookupResult(
                status=error.status,
                registered_at=None,
                source=None,
                error_code=error.error_code,
                retry_after=error.retry_after,
            )

        try:
            base_url = _select_authoritative_url(
                bootstrap,
                ascii_domain.rsplit(".", 1)[-1],
            )
        except _ClientFailure as error:
            if bootstrap.stale and error.status == "unsupported":
                return RdapLookupResult(
                    status="transient_error",
                    registered_at=None,
                    source=_RDAP_SOURCE,
                    error_code="rdap_service_unknown_via_stale_bootstrap",
                )
            return RdapLookupResult(
                status=error.status,
                registered_at=None,
                source=None,
                error_code=error.error_code,
                retry_after=error.retry_after,
            )

        endpoint_base = base_url.rstrip("/")
        endpoint_retry_after = self._get_endpoint_backoff(endpoint_base)
        if endpoint_retry_after is not None and endpoint_retry_after > now:
            return RdapLookupResult(
                status="transient_error",
                registered_at=None,
                source=_RDAP_SOURCE,
                error_code="rdap_endpoint_backoff",
                retry_after=endpoint_retry_after,
            )

        endpoint = f"{endpoint_base}/domain/{quote(ascii_domain, safe='.-')}"
        headers = {
            "Accept": "application/rdap+json",
            "User-Agent": _USER_AGENT,
        }

        try:
            response = self._transport.get(
                endpoint,
                headers=headers,
                timeout=HTTP_TIMEOUT_SECONDS,
                max_bytes=RDAP_MAX_BYTES,
            )
            _ensure_response_size(response, RDAP_MAX_BYTES)
        except ResponseTooLargeError:
            return RdapLookupResult(
                status="parse_error",
                registered_at=None,
                source=_RDAP_SOURCE,
                error_code="rdap_response_too_large",
            )
        except (OSError, TimeoutError, socket.timeout):
            retry_after = now + DEFAULT_ENDPOINT_BACKOFF_SECONDS
            self._put_endpoint_backoff(
                endpoint_base,
                retry_after=retry_after,
                observed_at=now,
            )
            return RdapLookupResult(
                status="transient_error",
                registered_at=None,
                source=_RDAP_SOURCE,
                error_code="rdap_network_error",
                retry_after=retry_after,
            )

        if response.status == 429 or 500 <= response.status <= 599:
            retry_after = _parse_retry_after(response.headers, now)
            if retry_after is None:
                retry_after = now + DEFAULT_ENDPOINT_BACKOFF_SECONDS
            self._put_endpoint_backoff(
                endpoint_base,
                retry_after=retry_after,
                observed_at=now,
            )

        return _interpret_domain_response(
            response,
            ascii_domain,
            now,
            authoritative_not_found=not bootstrap.stale,
        )

    def _load_bootstrap(self, now: int) -> _BootstrapData:
        # Domain lookups use separate single-flight stripes, so several first
        # requests can arrive here concurrently. Serialize bootstrap refreshes
        # to avoid a startup stampede against IANA; the cache is checked again
        # after acquiring the lock by the method below.
        with self._bootstrap_lock:
            return self._load_bootstrap_locked(now)

    def _load_bootstrap_locked(self, now: int) -> _BootstrapData:
        cached = self._get_cached_bootstrap()
        parsed_cached = _parse_cached_bootstrap(cached)
        stale_data = (
            parsed_cached
            if _bootstrap_is_within_stale_window(cached, now)
            else None
        )

        if (
            cached is not None
            and stale_data is not None
            and cached.fresh_until > now
        ):
            return stale_data

        bootstrap_retry_after = self._get_endpoint_backoff(
            IANA_DNS_BOOTSTRAP_URL
        )
        if bootstrap_retry_after is not None and bootstrap_retry_after > now:
            if stale_data is not None:
                return self._serve_stale_bootstrap(
                    cached,
                    stale_data,
                    now,
                    retry_after=bootstrap_retry_after,
                )
            raise _ClientFailure(
                "transient_error",
                "bootstrap_backoff",
                retry_after=bootstrap_retry_after,
            )

        headers = {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if cached is not None and stale_data is not None:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified

        try:
            response = self._transport.get(
                IANA_DNS_BOOTSTRAP_URL,
                headers=headers,
                timeout=HTTP_TIMEOUT_SECONDS,
                max_bytes=BOOTSTRAP_MAX_BYTES,
            )
            _ensure_response_size(response, BOOTSTRAP_MAX_BYTES)
        except ResponseTooLargeError:
            if stale_data is not None:
                return self._serve_stale_bootstrap(cached, stale_data, now)
            raise _ClientFailure("parse_error", "bootstrap_response_too_large")
        except (OSError, TimeoutError, socket.timeout):
            retry_after = now + BOOTSTRAP_FAILURE_BACKOFF_SECONDS
            self._put_endpoint_backoff(
                IANA_DNS_BOOTSTRAP_URL,
                retry_after=retry_after,
                observed_at=now,
            )
            if stale_data is not None:
                return self._serve_stale_bootstrap(
                    cached,
                    stale_data,
                    now,
                    retry_after=retry_after,
                )
            raise _ClientFailure(
                "transient_error",
                "bootstrap_network_error",
                retry_after=retry_after,
            )

        fresh_until = now + BOOTSTRAP_FRESHNESS_SECONDS

        if response.status == 304:
            if cached is None or stale_data is None:
                raise _ClientFailure(
                    "parse_error",
                    "bootstrap_304_without_valid_cache",
                )

            self._put_bootstrap(
                cached.payload,
                now,
                fresh_until,
                etag=_header(response.headers, "ETag") or cached.etag,
                last_modified=(
                    _header(response.headers, "Last-Modified")
                    or cached.last_modified
                ),
            )
            return _BootstrapData(stale_data.services, stale=False)

        if response.status == 200:
            try:
                payload = response.body.decode("utf-8")
                parsed = _parse_bootstrap(payload)
            except (UnicodeDecodeError, ValueError):
                if stale_data is not None:
                    return self._serve_stale_bootstrap(cached, stale_data, now)
                raise _ClientFailure("parse_error", "invalid_bootstrap_payload")

            self._put_bootstrap(
                payload,
                now,
                fresh_until,
                etag=_header(response.headers, "ETag"),
                last_modified=_header(response.headers, "Last-Modified"),
            )
            return parsed

        retry_after = (
            _parse_retry_after(response.headers, now)
            if response.status == 429 or 500 <= response.status <= 599
            else None
        )
        if response.status == 429 or 500 <= response.status <= 599:
            retry_after = retry_after or now + BOOTSTRAP_FAILURE_BACKOFF_SECONDS
            self._put_endpoint_backoff(
                IANA_DNS_BOOTSTRAP_URL,
                retry_after=retry_after,
                observed_at=now,
            )
        if stale_data is not None:
            return self._serve_stale_bootstrap(
                cached,
                stale_data,
                now,
                retry_after=retry_after,
            )

        if response.status == 429:
            raise _ClientFailure(
                "rate_limited",
                "bootstrap_rate_limited",
                retry_after=(
                    retry_after or now + BOOTSTRAP_FAILURE_BACKOFF_SECONDS
                ),
            )
        if 500 <= response.status <= 599:
            raise _ClientFailure(
                "transient_error",
                "bootstrap_server_error",
                retry_after=retry_after,
            )
        if 300 <= response.status <= 399:
            raise _ClientFailure("transient_error", "bootstrap_redirect_rejected")
        raise _ClientFailure("transient_error", "bootstrap_http_error")

    def _get_cached_bootstrap(self) -> BootstrapCacheEntry | None:
        try:
            return self._cache.get_bootstrap()
        except Exception:
            return None

    def _put_bootstrap(
        self,
        payload: str,
        fetched_at: int,
        fresh_until: int,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        try:
            self._cache.put_bootstrap(
                payload,
                fetched_at,
                fresh_until,
                etag=etag,
                last_modified=last_modified,
            )
        except Exception:
            # Persistence failure must not turn a valid authoritative response
            # into a failed security lookup.
            return

    def _serve_stale_bootstrap(
        self,
        cached: BootstrapCacheEntry | None,
        stale_data: _BootstrapData,
        now: int,
        *,
        retry_after: int | None = None,
    ) -> _BootstrapData:
        assert cached is not None
        cooldown_until = retry_after or now + BOOTSTRAP_FAILURE_BACKOFF_SECONDS
        stale_deadline = cached.fetched_at + BOOTSTRAP_STALE_MAX_AGE_SECONDS
        self._put_bootstrap(
            cached.payload,
            cached.fetched_at,
            min(cooldown_until, stale_deadline),
            etag=cached.etag,
            last_modified=cached.last_modified,
        )
        return _BootstrapData(stale_data.services, stale=True)

    def _get_endpoint_backoff(self, endpoint: str) -> int | None:
        try:
            getter = getattr(self._cache, "get_endpoint_backoff")
            value = getter(endpoint)
            return value if isinstance(value, int) else None
        except Exception:
            return None

    def _put_endpoint_backoff(
        self,
        endpoint: str,
        *,
        retry_after: int,
        observed_at: int,
    ) -> None:
        try:
            putter = getattr(self._cache, "put_endpoint_backoff")
            putter(endpoint, retry_after, observed_at)
        except Exception:
            return


def _read_limited(response: object, max_bytes: int) -> bytes:
    headers = getattr(response, "headers", {})
    content_length = _header(headers, "Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise ResponseTooLargeError
        except ValueError:
            pass

    body = response.read(max_bytes + 1)  # type: ignore[attr-defined]
    if len(body) > max_bytes:
        raise ResponseTooLargeError
    return body


def _ensure_response_size(response: TransportResponse, max_bytes: int) -> None:
    content_length = _header(response.headers, "Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise ResponseTooLargeError
        except ValueError:
            pass
    if len(response.body) > max_bytes:
        raise ResponseTooLargeError


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return value
    return None


def _epoch_seconds(value: datetime | int | float) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    return int(value)


def _normalize_domain(value: str) -> str | None:
    if not isinstance(value, str):
        return None

    candidate = value.strip().rstrip(".").lower()
    if not candidate or "/" in candidate or ":" in candidate:
        return None

    try:
        ipaddress.ip_address(candidate)
        return None
    except ValueError:
        pass

    try:
        ascii_domain = idna.encode(
            candidate,
            uts46=True,
            std3_rules=True,
        ).decode("ascii").lower()
    except (idna.IDNAError, ValueError):
        return None

    try:
        ipaddress.ip_address(ascii_domain)
        return None
    except ValueError:
        pass

    if len(ascii_domain) > 253 or "." not in ascii_domain:
        return None

    labels = ascii_domain.split(".")
    for label in labels:
        if not label or len(label) > 63:
            return None
        if label[0] == "-" or label[-1] == "-":
            return None
        if not all(character.isalnum() or character == "-" for character in label):
            return None

    return ascii_domain


def _parse_cached_bootstrap(entry: BootstrapCacheEntry | None) -> _BootstrapData | None:
    if entry is None:
        return None
    try:
        parsed = _parse_bootstrap(entry.payload)
        is_stale_cooldown = (
            entry.fresh_until
            > entry.fetched_at + BOOTSTRAP_FRESHNESS_SECONDS
        )
        return _BootstrapData(parsed.services, stale=is_stale_cooldown)
    except (TypeError, UnicodeDecodeError, ValueError):
        return None


def _bootstrap_is_within_stale_window(
    entry: BootstrapCacheEntry | None,
    now: int,
) -> bool:
    if entry is None:
        return False
    age = now - entry.fetched_at
    return 0 <= age < BOOTSTRAP_STALE_MAX_AGE_SECONDS


def _parse_bootstrap(payload: str | bytes) -> _BootstrapData:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    document = json.loads(payload)
    if not isinstance(document, dict) or not isinstance(document.get("services"), list):
        raise ValueError("Invalid IANA RDAP bootstrap document")

    services: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for raw_service in document["services"]:
        if not isinstance(raw_service, list) or len(raw_service) != 2:
            continue
        raw_entries, raw_urls = raw_service
        if not isinstance(raw_entries, list) or not isinstance(raw_urls, list):
            continue

        entries = tuple(
            entry.lower().rstrip(".")
            for entry in raw_entries
            if isinstance(entry, str) and entry
        )
        urls = tuple(url for url in raw_urls if isinstance(url, str) and url)
        if entries and urls:
            services.append((entries, urls))

    if not services:
        raise ValueError("IANA RDAP bootstrap contains no services")
    return _BootstrapData(tuple(services))


def _select_authoritative_url(bootstrap: _BootstrapData, tld: str) -> str:
    matching_urls: list[str] = []
    for entries, urls in bootstrap.services:
        if tld in entries:
            matching_urls.extend(urls)

    if not matching_urls:
        raise _ClientFailure("unsupported", "rdap_service_not_found")

    for url in matching_urls:
        if _is_safe_rdap_base_url(url):
            return url

    raise _ClientFailure("unsupported", "unsafe_rdap_endpoint")


def _is_safe_rdap_base_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False

    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.query or parsed.fragment:
        return False
    if port is not None and not (1 <= port <= 65535):
        return False

    hostname = parsed.hostname.rstrip(".")
    try:
        # URL resolvers apply IDNA mappings themselves. Perform the security
        # checks on that same ASCII form so Unicode dots or compatibility
        # characters cannot disguise localhost/private addresses.
        normalized_hostname = idna.encode(
            hostname,
            uts46=True,
            std3_rules=True,
        ).decode("ascii").casefold()
    except (idna.IDNAError, ValueError):
        return False
    if not normalized_hostname or len(normalized_hostname) > 253:
        return False
    if normalized_hostname == "localhost" or normalized_hostname.endswith(
        ".localhost"
    ):
        return False

    # Do not pre-resolve arbitrary names with getaddrinfo here. ``urllib`` would
    # resolve the hostname again while connecting, leaving a DNS-rebinding/TOCTOU
    # gap. Closing that gap requires a transport which connects to a vetted,
    # pinned address while retaining the original hostname for TLS SNI checks.
    try:
        address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        # ``urllib`` accepts legacy IPv4 spellings such as ``127.1`` and
        # ``2130706433``.  Treat them as literals too, otherwise they can hide
        # a loopback/private endpoint from the ordinary ipaddress parser.
        try:
            address = ipaddress.ip_address(socket.inet_aton(normalized_hostname))
        except OSError:
            labels = normalized_hostname.split(".")
            return all(
                label
                and len(label) <= 63
                and label[0] != "-"
                and label[-1] != "-"
                and all(character.isalnum() or character == "-" for character in label)
                for label in labels
            )
    return address.is_global


def _interpret_domain_response(
    response: TransportResponse,
    ascii_domain: str,
    now: int,
    *,
    authoritative_not_found: bool = True,
) -> RdapLookupResult:
    if response.status == 304:
        return RdapLookupResult(
            "transient_error",
            None,
            _RDAP_SOURCE,
            error_code="rdap_304_without_cached_response",
        )
    if response.status == 404:
        if not authoritative_not_found:
            return RdapLookupResult(
                "transient_error",
                None,
                _RDAP_SOURCE,
                error_code="rdap_not_found_via_stale_bootstrap",
            )
        return RdapLookupResult("not_found", None, _RDAP_SOURCE)
    if response.status == 429:
        retry_after = _parse_retry_after(response.headers, now)
        return RdapLookupResult(
            "rate_limited",
            None,
            _RDAP_SOURCE,
            error_code="rdap_rate_limited",
            retry_after=(retry_after or now + DEFAULT_ENDPOINT_BACKOFF_SECONDS),
        )
    if 500 <= response.status <= 599:
        retry_after = _parse_retry_after(response.headers, now)
        return RdapLookupResult(
            "transient_error",
            None,
            _RDAP_SOURCE,
            error_code="rdap_server_error",
            retry_after=(retry_after or now + DEFAULT_ENDPOINT_BACKOFF_SECONDS),
        )
    if 300 <= response.status <= 399:
        return RdapLookupResult(
            "transient_error",
            None,
            _RDAP_SOURCE,
            error_code="rdap_redirect_rejected",
        )
    if response.status != 200:
        return RdapLookupResult(
            "transient_error",
            None,
            _RDAP_SOURCE,
            error_code="rdap_http_error",
        )

    try:
        document = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return RdapLookupResult(
            "parse_error",
            None,
            _RDAP_SOURCE,
            error_code="invalid_rdap_payload",
        )

    if not isinstance(document, dict):
        return RdapLookupResult(
            "parse_error",
            None,
            _RDAP_SOURCE,
            error_code="invalid_rdap_payload",
        )

    name_error = _validate_response_domain(document, ascii_domain)
    if name_error is not None:
        return RdapLookupResult(
            "parse_error",
            None,
            _RDAP_SOURCE,
            error_code=name_error,
        )

    events = document.get("events")
    if events is None:
        return RdapLookupResult(
            "missing_registration_date",
            None,
            _RDAP_SOURCE,
            error_code="registration_event_missing",
        )
    if not isinstance(events, list):
        return RdapLookupResult(
            "parse_error",
            None,
            _RDAP_SOURCE,
            error_code="invalid_rdap_events",
        )

    registration_dates: list[datetime] = []
    registration_event_seen = False
    for event in events:
        if not isinstance(event, dict):
            continue
        action = event.get("eventAction")
        if not isinstance(action, str) or action.casefold() != "registration":
            continue
        registration_event_seen = True
        parsed_date = _parse_rdap_datetime(event.get("eventDate"))
        if parsed_date is not None:
            registration_dates.append(parsed_date)

    if not registration_dates:
        if registration_event_seen:
            return RdapLookupResult(
                "parse_error",
                None,
                _RDAP_SOURCE,
                error_code="malformed_registration_date",
            )
        return RdapLookupResult(
            "missing_registration_date",
            None,
            _RDAP_SOURCE,
            error_code="registration_date_missing",
        )

    return RdapLookupResult(
        status="success",
        registered_at=min(registration_dates),
        source=_RDAP_SOURCE,
    )


def _validate_response_domain(
    document: Mapping[str, object],
    expected: str,
) -> str | None:
    found_name = False
    for key in ("ldhName", "unicodeName"):
        if key not in document:
            continue
        value = document[key]
        if not isinstance(value, str):
            return "invalid_rdap_domain_name"
        found_name = True
        if _normalize_domain(value) != expected:
            return "rdap_domain_mismatch"

    if not found_name:
        return "rdap_domain_name_missing"
    return None


def _parse_rdap_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_retry_after(headers: Mapping[str, str], now: int) -> int | None:
    value = _header(headers, "Retry-After")
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        if len(value) > 10:
            return now + MAX_RETRY_AFTER_SECONDS
        candidate = now + int(value)
        return _bound_retry_after(candidate, now)
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        candidate = int(parsed.timestamp())
    except (OSError, OverflowError, ValueError):
        return None
    return _bound_retry_after(candidate, now)


def _bound_retry_after(candidate: int, now: int) -> int | None:
    if candidate <= now:
        return None
    return min(candidate, now + MAX_RETRY_AFTER_SECONDS)
