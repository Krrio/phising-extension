from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Mapping

from guardian_classic.domain_cache import DomainRegistrationCache
from guardian_classic.rdap_client import (
    BOOTSTRAP_FAILURE_BACKOFF_SECONDS,
    BOOTSTRAP_FRESHNESS_SECONDS,
    BOOTSTRAP_MAX_BYTES,
    BOOTSTRAP_STALE_MAX_AGE_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    IANA_DNS_BOOTSTRAP_URL,
    MAX_RETRY_AFTER_SECONDS,
    RDAP_MAX_BYTES,
    RdapClient,
    TransportResponse,
)


NOW = 1_700_000_000
RDAP_BASE_URL = "https://rdap.example.test/registry/"


@dataclass(frozen=True, slots=True)
class FakeBootstrapEntry:
    payload: str
    fetched_at: int
    fresh_until: int
    etag: str | None = None
    last_modified: str | None = None


class FakeCache:
    def __init__(self, entry: FakeBootstrapEntry | None = None) -> None:
        self.entry = entry
        self.puts: list[FakeBootstrapEntry] = []
        self.endpoint_backoffs: dict[str, tuple[int, int]] = {}

    def get_bootstrap(self) -> FakeBootstrapEntry | None:
        return self.entry

    def put_bootstrap(
        self,
        payload: str,
        fetched_at: int,
        fresh_until: int,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        entry = FakeBootstrapEntry(
            payload=payload,
            fetched_at=fetched_at,
            fresh_until=fresh_until,
            etag=etag,
            last_modified=last_modified,
        )
        self.entry = entry
        self.puts.append(entry)

    def get_endpoint_backoff(self, endpoint: str) -> int | None:
        stored = self.endpoint_backoffs.get(endpoint.rstrip("/"))
        return None if stored is None else stored[0]

    def put_endpoint_backoff(
        self,
        endpoint: str,
        retry_after: int,
        observed_at: int,
    ) -> None:
        self.endpoint_backoffs[endpoint.rstrip("/")] = (
            retry_after,
            observed_at,
        )


@dataclass(frozen=True, slots=True)
class TransportCall:
    url: str
    headers: Mapping[str, str]
    timeout: float
    max_bytes: int


class FakeTransport:
    def __init__(self, *responses: TransportResponse | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[TransportCall] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> TransportResponse:
        self.calls.append(TransportCall(url, dict(headers), timeout, max_bytes))
        if not self.responses:
            raise AssertionError(f"Unexpected HTTP call: {url}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def response(
    status: int,
    body: bytes | str = b"",
    headers: Mapping[str, str] | None = None,
) -> TransportResponse:
    if isinstance(body, str):
        body = body.encode("utf-8")
    return TransportResponse(status=status, headers=headers or {}, body=body)


def bootstrap_payload(
    *,
    tlds: tuple[str, ...] = ("com",),
    urls: tuple[str, ...] = (RDAP_BASE_URL,),
) -> str:
    return json.dumps({"services": [[list(tlds), list(urls)]]})


def rdap_payload(
    domain: str = "example.com",
    *,
    unicode_name: str | None = None,
    events: object | None = None,
) -> str:
    if events is None:
        events = [
            {
                "eventAction": "registration",
                "eventDate": "2020-01-02T03:04:05Z",
            }
        ]
    document: dict[str, object] = {"ldhName": domain, "events": events}
    if unicode_name is not None:
        document["unicodeName"] = unicode_name
    return json.dumps(document)


def fresh_cache(
    *,
    tlds: tuple[str, ...] = ("com",),
    urls: tuple[str, ...] = (RDAP_BASE_URL,),
) -> FakeCache:
    return FakeCache(
        FakeBootstrapEntry(
            bootstrap_payload(tlds=tlds, urls=urls),
            fetched_at=NOW - 60,
            fresh_until=NOW + 60,
        )
    )


class RdapClientResultTests(unittest.TestCase):
    def lookup(
        self,
        domain: str,
        rdap_response: TransportResponse,
        *,
        tlds: tuple[str, ...] = ("com",),
    ):
        transport = FakeTransport(rdap_response)
        client = RdapClient(
            fresh_cache(tlds=tlds),
            transport=transport,
            clock=lambda: NOW,
        )
        return client.lookup(domain), transport

    def test_success_uses_earliest_valid_registration_event(self) -> None:
        events = [
            {"eventAction": "last changed", "eventDate": "2019-01-01T00:00:00Z"},
            {"eventAction": "registration", "eventDate": "not-a-date"},
            {
                "eventAction": "registration",
                "eventDate": "2021-04-05T14:00:00+02:00",
            },
            {"eventAction": "registration", "eventDate": "2020-01-02T03:04:05Z"},
        ]

        result, transport = self.lookup(
            "EXAMPLE.COM.",
            response(200, rdap_payload(events=events)),
        )

        self.assertEqual("success", result.status)
        self.assertEqual("rdap", result.source)
        self.assertEqual(
            datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            result.registered_at,
        )
        self.assertEqual(
            "https://rdap.example.test/registry/domain/example.com",
            transport.calls[0].url,
        )
        self.assertEqual("application/rdap+json", transport.calls[0].headers["Accept"])
        self.assertEqual(HTTP_TIMEOUT_SECONDS, transport.calls[0].timeout)
        self.assertEqual(RDAP_MAX_BYTES, transport.calls[0].max_bytes)

    def test_not_found(self) -> None:
        result, _ = self.lookup("example.com", response(404))
        self.assertEqual("not_found", result.status)
        self.assertIsNone(result.registered_at)

    def test_rate_limited_parses_delta_retry_after(self) -> None:
        result, _ = self.lookup(
            "example.com",
            response(429, headers={"retry-after": "120"}),
        )
        self.assertEqual("rate_limited", result.status)
        self.assertEqual(NOW + 120, result.retry_after)

    def test_rate_limited_parses_http_date_retry_after(self) -> None:
        retry_at = datetime(2023, 11, 14, 23, 0, tzinfo=timezone.utc)
        result, _ = self.lookup(
            "example.com",
            response(429, headers={"Retry-After": format_datetime(retry_at)}),
        )
        self.assertEqual(int(retry_at.timestamp()), result.retry_after)

    def test_retry_after_is_bounded_and_huge_digits_do_not_raise(self) -> None:
        result, _ = self.lookup(
            "example.com",
            response(429, headers={"Retry-After": "9" * 5_000}),
        )

        self.assertEqual("rate_limited", result.status)
        self.assertEqual(NOW + MAX_RETRY_AFTER_SECONDS, result.retry_after)

    def test_server_retry_after_is_propagated(self) -> None:
        result, _ = self.lookup(
            "example.com",
            response(503, headers={"Retry-After": "600"}),
        )

        self.assertEqual("transient_error", result.status)
        self.assertEqual(NOW + 600, result.retry_after)

    def test_server_error_is_transient(self) -> None:
        result, _ = self.lookup("example.com", response(503))
        self.assertEqual("transient_error", result.status)
        self.assertEqual("rdap_server_error", result.error_code)

    def test_not_modified_without_cached_rdap_response_is_transient(self) -> None:
        result, _ = self.lookup("example.com", response(304))
        self.assertEqual("transient_error", result.status)
        self.assertEqual("rdap_304_without_cached_response", result.error_code)

    def test_invalid_json_is_parse_error(self) -> None:
        result, _ = self.lookup("example.com", response(200, "{"))
        self.assertEqual("parse_error", result.status)
        self.assertEqual("invalid_rdap_payload", result.error_code)

    def test_missing_registration_date_has_distinct_status(self) -> None:
        result, _ = self.lookup(
            "example.com",
            response(
                200,
                rdap_payload(
                    events=[
                        {
                            "eventAction": "last changed",
                            "eventDate": "2020-01-01T00:00:00Z",
                        }
                    ]
                ),
            ),
        )
        self.assertEqual("missing_registration_date", result.status)
        self.assertEqual("registration_date_missing", result.error_code)

    def test_malformed_registration_date_is_not_treated_as_missing(self) -> None:
        result, _ = self.lookup(
            "example.com",
            response(
                200,
                rdap_payload(
                    events=[
                        {
                            "eventAction": "registration",
                            "eventDate": "not-a-date",
                        }
                    ]
                ),
            ),
        )

        self.assertEqual("parse_error", result.status)
        self.assertEqual("malformed_registration_date", result.error_code)

    def test_other_authoritative_http_errors_are_transient(self) -> None:
        for status in (400, 401, 403, 405, 410, 418):
            with self.subTest(status=status):
                result, _ = self.lookup("example.com", response(status))
                self.assertEqual("transient_error", result.status)
                self.assertEqual("rdap_http_error", result.error_code)

    def test_network_failure_is_transient(self) -> None:
        transport = FakeTransport(OSError("offline"))
        client = RdapClient(
            fresh_cache(),
            transport=transport,
            clock=lambda: NOW,
        )
        result = client.lookup("example.com")
        self.assertEqual("transient_error", result.status)
        self.assertEqual("rdap_network_error", result.error_code)


class RdapClientBootstrapTests(unittest.TestCase):
    def test_fresh_bootstrap_cache_skips_iana_request(self) -> None:
        transport = FakeTransport(response(404))
        client = RdapClient(
            fresh_cache(),
            transport=transport,
            clock=lambda: NOW,
        )

        self.assertEqual("not_found", client.lookup("example.com").status)
        self.assertEqual(1, len(transport.calls))
        self.assertNotEqual(IANA_DNS_BOOTSTRAP_URL, transport.calls[0].url)

    def test_bootstrap_200_is_validated_and_persisted_for_24_hours(self) -> None:
        payload = bootstrap_payload()
        cache = FakeCache()
        transport = FakeTransport(
            response(
                200,
                payload,
                {"ETag": '"bootstrap-v1"', "Last-Modified": "yesterday"},
            ),
            response(404),
        )
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)

        result = client.lookup("example.com")

        self.assertEqual("not_found", result.status)
        self.assertEqual(IANA_DNS_BOOTSTRAP_URL, transport.calls[0].url)
        self.assertEqual(BOOTSTRAP_MAX_BYTES, transport.calls[0].max_bytes)
        self.assertEqual(1, len(cache.puts))
        self.assertEqual(NOW, cache.puts[0].fetched_at)
        self.assertEqual(NOW + BOOTSTRAP_FRESHNESS_SECONDS, cache.puts[0].fresh_until)
        self.assertEqual('"bootstrap-v1"', cache.puts[0].etag)
        self.assertEqual("yesterday", cache.puts[0].last_modified)

    def test_sqlite_cache_protocol_survives_a_new_cache_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "registration-cache.db"
            first_transport = FakeTransport(
                response(200, bootstrap_payload(), {"ETag": '"persistent"'}),
                response(404),
            )
            first_client = RdapClient(
                DomainRegistrationCache(database_path),
                transport=first_transport,
                clock=lambda: NOW,
            )
            self.assertEqual("not_found", first_client.lookup("example.com").status)

            second_transport = FakeTransport(response(404))
            second_client = RdapClient(
                DomainRegistrationCache(database_path),
                transport=second_transport,
                clock=lambda: NOW + 1,
            )
            self.assertEqual("not_found", second_client.lookup("example.com").status)
            self.assertEqual(1, len(second_transport.calls))
            self.assertNotEqual(
                IANA_DNS_BOOTSTRAP_URL,
                second_transport.calls[0].url,
            )

    def test_stale_bootstrap_uses_conditional_headers_and_304_refreshes_it(
        self,
    ) -> None:
        cached = FakeBootstrapEntry(
            bootstrap_payload(),
            fetched_at=NOW - 100_000,
            fresh_until=NOW - 1,
            etag='"old-etag"',
            last_modified="old-date",
        )
        cache = FakeCache(cached)
        transport = FakeTransport(
            response(304, headers={"ETag": '"new-etag"'}),
            response(404),
        )
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)

        result = client.lookup("example.com")

        self.assertEqual("not_found", result.status)
        self.assertEqual('"old-etag"', transport.calls[0].headers["If-None-Match"])
        self.assertEqual("old-date", transport.calls[0].headers["If-Modified-Since"])
        self.assertEqual('"new-etag"', cache.puts[0].etag)
        self.assertEqual("old-date", cache.puts[0].last_modified)
        self.assertEqual(NOW + BOOTSTRAP_FRESHNESS_SECONDS, cache.puts[0].fresh_until)

    def test_stale_bootstrap_is_used_when_refresh_fails(self) -> None:
        cache = FakeCache(
            FakeBootstrapEntry(
                bootstrap_payload(),
                fetched_at=NOW - 100_000,
                fresh_until=NOW - 1,
                etag='"v1"',
            )
        )
        transport = FakeTransport(OSError("offline"), response(404))
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)

        result = client.lookup("example.com")

        self.assertEqual("transient_error", result.status)
        self.assertEqual("rdap_not_found_via_stale_bootstrap", result.error_code)
        self.assertEqual(2, len(transport.calls))
        self.assertEqual(IANA_DNS_BOOTSTRAP_URL, transport.calls[0].url)
        self.assertEqual(NOW - 100_000, cache.puts[0].fetched_at)
        self.assertEqual(
            NOW + BOOTSTRAP_FAILURE_BACKOFF_SECONDS,
            cache.puts[0].fresh_until,
        )

    def test_stale_bootstrap_backoff_avoids_repeated_iana_requests(self) -> None:
        cache = FakeCache(
            FakeBootstrapEntry(
                bootstrap_payload(),
                fetched_at=NOW - 100_000,
                fresh_until=NOW - 1,
            )
        )
        transport = FakeTransport(
            OSError("offline"),
            response(404),
            response(404),
        )
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)

        self.assertEqual("transient_error", client.lookup("example.com").status)
        self.assertEqual("transient_error", client.lookup("other.com").status)

        iana_calls = [
            call for call in transport.calls if call.url == IANA_DNS_BOOTSTRAP_URL
        ]
        self.assertEqual(1, len(iana_calls))

    def test_unknown_service_in_stale_bootstrap_is_not_authoritative(self) -> None:
        cache = FakeCache(
            FakeBootstrapEntry(
                bootstrap_payload(tlds=("com",)),
                fetched_at=NOW - 100_000,
                fresh_until=NOW - 1,
            )
        )
        transport = FakeTransport(OSError("offline"))
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)

        result = client.lookup("example.net")

        self.assertEqual("transient_error", result.status)
        self.assertEqual(
            "rdap_service_unknown_via_stale_bootstrap",
            result.error_code,
        )
        self.assertEqual(1, len(transport.calls))

    def test_bootstrap_older_than_stale_limit_is_not_used(self) -> None:
        cache = FakeCache(
            FakeBootstrapEntry(
                bootstrap_payload(),
                fetched_at=NOW - BOOTSTRAP_STALE_MAX_AGE_SECONDS,
                fresh_until=NOW + 60,
            )
        )
        transport = FakeTransport(OSError("offline"))
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)

        result = client.lookup("example.com")

        self.assertEqual("transient_error", result.status)
        self.assertEqual("bootstrap_network_error", result.error_code)

    def test_stale_bootstrap_is_used_when_new_payload_is_oversized(self) -> None:
        cache = FakeCache(
            FakeBootstrapEntry(
                bootstrap_payload(),
                fetched_at=NOW - 100_000,
                fresh_until=NOW - 1,
            )
        )
        transport = FakeTransport(
            response(200, b"x" * (BOOTSTRAP_MAX_BYTES + 1)),
            response(404),
        )
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)

        result = client.lookup("example.com")
        self.assertEqual("transient_error", result.status)
        self.assertEqual("rdap_not_found_via_stale_bootstrap", result.error_code)
        self.assertEqual(1, len(cache.puts))

    def test_304_without_cached_payload_is_parse_error(self) -> None:
        transport = FakeTransport(response(304))
        client = RdapClient(FakeCache(), transport=transport, clock=lambda: NOW)
        result = client.lookup("example.com")
        self.assertEqual("parse_error", result.status)
        self.assertEqual("bootstrap_304_without_valid_cache", result.error_code)

    def test_bootstrap_rate_limit_without_stale_cache(self) -> None:
        transport = FakeTransport(response(429, headers={"Retry-After": "60"}))
        cache = FakeCache()
        client = RdapClient(cache, transport=transport, clock=lambda: NOW)
        result = client.lookup("example.com")
        self.assertEqual("rate_limited", result.status)
        self.assertEqual(NOW + 60, result.retry_after)

        second_transport = FakeTransport()
        second = RdapClient(cache, transport=second_transport, clock=lambda: NOW)
        blocked = second.lookup("other.com")
        self.assertEqual("transient_error", blocked.status)
        self.assertEqual("bootstrap_backoff", blocked.error_code)
        self.assertEqual(NOW + 60, blocked.retry_after)
        self.assertEqual([], second_transport.calls)

    def test_bootstrap_4xx_without_stale_cache_is_transient(self) -> None:
        transport = FakeTransport(response(403))
        client = RdapClient(FakeCache(), transport=transport, clock=lambda: NOW)
        result = client.lookup("example.com")
        self.assertEqual("transient_error", result.status)
        self.assertEqual("bootstrap_http_error", result.error_code)


class RdapClientDomainAndSecurityTests(unittest.TestCase):
    def test_compound_suffix_uses_tld_bootstrap_and_queries_complete_domain(
        self,
    ) -> None:
        transport = FakeTransport(response(200, rdap_payload("example.co.uk")))
        client = RdapClient(
            fresh_cache(tlds=("uk",)),
            transport=transport,
            clock=lambda: NOW,
        )

        result = client.lookup("example.co.uk")

        self.assertEqual("success", result.status)
        self.assertTrue(transport.calls[0].url.endswith("/domain/example.co.uk"))

    def test_idn_is_queried_as_ascii_and_unicode_name_is_verified(self) -> None:
        ascii_domain = "xn--mnich-kva.de"
        transport = FakeTransport(
            response(
                200,
                rdap_payload(ascii_domain, unicode_name="MÜNICH.DE."),
            )
        )
        client = RdapClient(
            fresh_cache(tlds=("de",)),
            transport=transport,
            clock=lambda: NOW,
        )

        result = client.lookup("münich.de")

        self.assertEqual("success", result.status)
        self.assertTrue(transport.calls[0].url.endswith(f"/domain/{ascii_domain}"))

    def test_idna_2008_does_not_map_sharp_s_to_ss(self) -> None:
        ascii_domain = "xn--fa-hia.de"
        transport = FakeTransport(response(200, rdap_payload(ascii_domain)))
        client = RdapClient(
            fresh_cache(tlds=("de",)),
            transport=transport,
            clock=lambda: NOW,
        )

        result = client.lookup("faß.de")

        self.assertEqual("success", result.status)
        self.assertTrue(transport.calls[0].url.endswith(f"/domain/{ascii_domain}"))

    def test_endpoint_backoff_applies_across_domains_and_clients(self) -> None:
        cache = fresh_cache()
        first_transport = FakeTransport(response(429, headers={"Retry-After": "60"}))
        first = RdapClient(cache, transport=first_transport, clock=lambda: NOW)
        self.assertEqual("rate_limited", first.lookup("a.com").status)

        second_transport = FakeTransport()
        second = RdapClient(cache, transport=second_transport, clock=lambda: NOW)
        result = second.lookup("b.com")

        self.assertEqual("transient_error", result.status)
        self.assertEqual("rdap_endpoint_backoff", result.error_code)
        self.assertEqual(NOW + 60, result.retry_after)
        self.assertEqual([], second_transport.calls)

    def test_response_domain_mismatch_is_rejected(self) -> None:
        result_transport = FakeTransport(response(200, rdap_payload("attacker.com")))
        client = RdapClient(
            fresh_cache(),
            transport=result_transport,
            clock=lambda: NOW,
        )
        result = client.lookup("example.com")
        self.assertEqual("parse_error", result.status)
        self.assertEqual("rdap_domain_mismatch", result.error_code)

    def test_redirect_is_not_followed(self) -> None:
        transport = FakeTransport(
            response(
                302,
                headers={"Location": "https://other.example/domain/example.com"},
            )
        )
        client = RdapClient(
            fresh_cache(),
            transport=transport,
            clock=lambda: NOW,
        )
        result = client.lookup("example.com")
        self.assertEqual("transient_error", result.status)
        self.assertEqual("rdap_redirect_rejected", result.error_code)
        self.assertEqual(1, len(transport.calls))

    def test_non_https_authoritative_endpoint_is_rejected_without_request(self) -> None:
        transport = FakeTransport()
        client = RdapClient(
            fresh_cache(urls=("http://rdap.example.test/",)),
            transport=transport,
            clock=lambda: NOW,
        )
        result = client.lookup("example.com")
        self.assertEqual("unsupported", result.status)
        self.assertEqual("unsafe_rdap_endpoint", result.error_code)
        self.assertEqual([], transport.calls)

    def test_private_literal_ip_endpoint_is_rejected_without_request(self) -> None:
        for endpoint in (
            "https://127.0.0.1/rdap/",
            "https://127.1/rdap/",
            "https://2130706433/rdap/",
            "https://[::1]/rdap/",
            "https://10.1.2.3/rdap/",
        ):
            with self.subTest(endpoint=endpoint):
                transport = FakeTransport()
                client = RdapClient(
                    fresh_cache(urls=(endpoint,)),
                    transport=transport,
                    clock=lambda: NOW,
                )
                result = client.lookup("example.com")
                self.assertEqual("unsupported", result.status)
                self.assertEqual("unsafe_rdap_endpoint", result.error_code)
                self.assertEqual([], transport.calls)

    def test_localhost_endpoint_is_rejected_without_dns_or_request(self) -> None:
        for endpoint in (
            "https://localhost/rdap/",
            "https://registry.localhost/rdap/",
            "https://ⓛocalhost/rdap/",
            "https://127。0。0。1/rdap/",
        ):
            with self.subTest(endpoint=endpoint):
                transport = FakeTransport()
                client = RdapClient(
                    fresh_cache(urls=(endpoint,)),
                    transport=transport,
                    clock=lambda: NOW,
                )
                result = client.lookup("example.com")
                self.assertEqual("unsupported", result.status)
                self.assertEqual("unsafe_rdap_endpoint", result.error_code)
                self.assertEqual([], transport.calls)

    def test_first_safe_https_endpoint_is_selected(self) -> None:
        transport = FakeTransport(response(404))
        client = RdapClient(
            fresh_cache(
                urls=(
                    "http://rdap.example.test/",
                    "https://127.0.0.1/",
                    "https://safe.example.test/rdap/",
                )
            ),
            transport=transport,
            clock=lambda: NOW,
        )
        result = client.lookup("example.com")
        self.assertEqual("not_found", result.status)
        self.assertEqual(
            "https://safe.example.test/rdap/domain/example.com",
            transport.calls[0].url,
        )

    def test_oversized_rdap_response_is_rejected_before_json_parsing(self) -> None:
        transport = FakeTransport(response(200, b"{" + b" " * RDAP_MAX_BYTES))
        client = RdapClient(
            fresh_cache(),
            transport=transport,
            clock=lambda: NOW,
        )
        result = client.lookup("example.com")
        self.assertEqual("parse_error", result.status)
        self.assertEqual("rdap_response_too_large", result.error_code)

    def test_unknown_tld_is_unsupported_without_rdap_request(self) -> None:
        transport = FakeTransport()
        client = RdapClient(
            fresh_cache(tlds=("com",)),
            transport=transport,
            clock=lambda: NOW,
        )
        result = client.lookup("example.invalid")
        self.assertEqual("unsupported", result.status)
        self.assertEqual("rdap_service_not_found", result.error_code)
        self.assertEqual([], transport.calls)

    def test_invalid_domain_is_rejected_before_bootstrap_or_rdap(self) -> None:
        for domain in (
            "localhost",
            "127.0.0.1",
            "127。0。0。1",
            "https://example.com",
            "-bad.com",
        ):
            with self.subTest(domain=domain):
                transport = FakeTransport()
                client = RdapClient(
                    fresh_cache(),
                    transport=transport,
                    clock=lambda: NOW,
                )
                result = client.lookup(domain)
                self.assertEqual("parse_error", result.status)
                self.assertEqual("invalid_domain", result.error_code)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
