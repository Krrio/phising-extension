from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from guardian_classic.domain_registration import (
    ESTABLISHED_SUCCESS_FRESH_TTL,
    ESTABLISHED_SUCCESS_STALE_TTL,
    NOT_FOUND_TTL,
    PARSER_VERSION,
    PARSE_ERROR_TTL,
    RECENT_SUCCESS_FRESH_TTL,
    RECENT_SUCCESS_STALE_TTL,
    TRANSIENT_ERROR_TTL,
    UNSUPPORTED_TTL,
    YOUNG_SUCCESS_FRESH_TTL,
    YOUNG_SUCCESS_STALE_TTL,
    DomainRegistrationService,
    _default_cache_path,
    _default_whois_lookup,
)


UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class FakeCacheEntry:
    domain: str
    status: str
    registered_at: int | None
    source: str | None
    fetched_at: int
    fresh_until: int
    stale_until: int | None
    retry_after: int | None
    last_accessed_at: int
    error_code: str | None
    parser_version: int = PARSER_VERSION


class FakeCache:
    def __init__(self) -> None:
        self.entries: dict[str, FakeCacheEntry] = {}
        self.get_calls: list[str] = []
        self.success_writes = 0
        self.failure_writes = 0
        self.postpone_calls = 0
        self.touch_calls = 0
        self.prune_calls = 0
        self._lock = threading.Lock()

    def get(self, domain: str) -> FakeCacheEntry | None:
        with self._lock:
            self.get_calls.append(domain)
            return self.entries.get(domain)

    def put_success(
        self,
        *,
        domain: str,
        registered_at: int,
        source: str,
        fetched_at: int,
        fresh_until: int,
        stale_until: int,
        parser_version: int,
    ) -> None:
        with self._lock:
            self.success_writes += 1
            self.entries[domain] = FakeCacheEntry(
                domain=domain,
                status="success",
                registered_at=registered_at,
                source=source,
                fetched_at=fetched_at,
                fresh_until=fresh_until,
                stale_until=stale_until,
                retry_after=None,
                last_accessed_at=fetched_at,
                error_code=None,
                parser_version=parser_version,
            )

    def put_failure(
        self,
        *,
        domain: str,
        status: str,
        source: str | None,
        fetched_at: int,
        fresh_until: int,
        retry_after: int | None,
        error_code: str | None,
        parser_version: int,
    ) -> None:
        with self._lock:
            self.failure_writes += 1
            self.entries[domain] = FakeCacheEntry(
                domain=domain,
                status=status,
                registered_at=None,
                source=source,
                fetched_at=fetched_at,
                fresh_until=fresh_until,
                stale_until=None,
                retry_after=retry_after,
                last_accessed_at=fetched_at,
                error_code=error_code,
                parser_version=parser_version,
            )

    def postpone_retry(
        self,
        domain: str,
        *,
        retry_after: int,
        last_accessed_at: int | None = None,
        error_code: str | None = None,
    ) -> bool:
        with self._lock:
            self.postpone_calls += 1
            current = self.entries.get(domain)
            if current is None or current.status != "success":
                return False
            self.entries[domain] = replace(
                current,
                retry_after=retry_after,
                last_accessed_at=last_accessed_at or current.last_accessed_at,
                error_code=error_code,
            )
            return True

    def touch(self, domain: str, *, now: int) -> bool:
        with self._lock:
            self.touch_calls += 1
            current = self.entries.get(domain)
            if current is None:
                return False
            self.entries[domain] = replace(current, last_accessed_at=now)
            return True

    def prune(self, *, now: int) -> int:
        del now
        with self._lock:
            self.prune_calls += 1
        return 0


class ExplodingCache:
    def __getattr__(self, name: str):
        def explode(*args, **kwargs):
            del args, kwargs
            raise RuntimeError(f"cache {name} failed")

        return explode


@dataclass(frozen=True, slots=True)
class FakeRdapResult:
    status: str
    registered_at: datetime | None = None
    source: str | None = "rdap"
    error_code: str | None = None
    retry_after: int | None = None


class FakeRdapClient:
    def __init__(self, result: FakeRdapResult) -> None:
        self.result = result
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def lookup(self, domain: str) -> FakeRdapResult:
        with self._lock:
            self.calls.append(domain)
        return self.result


class BlockingRdapClient(FakeRdapClient):
    def __init__(self, result: FakeRdapResult) -> None:
        super().__init__(result)
        self.entered = threading.Event()
        self.release = threading.Event()

    def lookup(self, domain: str) -> FakeRdapResult:
        with self._lock:
            self.calls.append(domain)
        self.entered.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test did not release RDAP lookup")
        return self.result


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


class DomainRegistrationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
        self.clock = MutableClock(self.now)

    def service(
        self,
        rdap_result: FakeRdapResult,
        *,
        cache: FakeCache | ExplodingCache | None = None,
        whois_lookup=None,
    ) -> tuple[DomainRegistrationService, FakeCache | ExplodingCache, FakeRdapClient]:
        selected_cache = cache or FakeCache()
        rdap = FakeRdapClient(rdap_result)
        service = DomainRegistrationService(
            selected_cache,
            rdap,
            whois_lookup=whois_lookup or (lambda domain: None),
            clock=self.clock,
            rng=lambda: 0.5,
        )
        return service, selected_cache, rdap

    def success_entry(
        self,
        domain: str,
        *,
        fresh_until: datetime,
        stale_until: datetime,
        registered_at: datetime | None = None,
        retry_after: datetime | None = None,
    ) -> FakeCacheEntry:
        registered_at = registered_at or datetime(2020, 1, 1, tzinfo=UTC)
        return FakeCacheEntry(
            domain=domain,
            status="success",
            registered_at=int(registered_at.timestamp()),
            source="rdap",
            fetched_at=int((self.now - timedelta(days=31)).timestamp()),
            fresh_until=int(fresh_until.timestamp()),
            stale_until=int(stale_until.timestamp()),
            retry_after=(
                int(retry_after.timestamp()) if retry_after is not None else None
            ),
            last_accessed_at=int(self.now.timestamp()),
            error_code=None,
        )

    def test_fresh_cache_uses_registrable_co_uk_key(self) -> None:
        cache = FakeCache()
        cache.entries["example.co.uk"] = self.success_entry(
            "example.co.uk",
            fresh_until=self.now + timedelta(days=1),
            stale_until=self.now + timedelta(days=100),
        )
        service, _, rdap = self.service(
            FakeRdapResult("transient_error", error_code="timeout"),
            cache=cache,
        )

        result = service.lookup("HTTPS://WWW.Example.CO.UK/account")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.domain, "example.co.uk")
        self.assertFalse(result.stale)
        self.assertEqual(rdap.calls, [])
        self.assertEqual(cache.get_calls, ["example.co.uk"])
        self.assertEqual(cache.touch_calls, 0)

    def test_fresh_cache_touch_is_coalesced_to_one_write_per_hour(self) -> None:
        cache = FakeCache()
        entry = self.success_entry(
            "example.com",
            fresh_until=self.now + timedelta(days=1),
            stale_until=self.now + timedelta(days=100),
        )
        cache.entries["example.com"] = replace(
            entry,
            last_accessed_at=int((self.now - timedelta(hours=1)).timestamp()),
        )
        service, _, rdap = self.service(
            FakeRdapResult("transient_error", error_code="timeout"),
            cache=cache,
        )

        result = service.lookup("example.com")

        self.assertEqual(result.status, "success")
        self.assertEqual(rdap.calls, [])
        self.assertEqual(cache.touch_calls, 1)

    def test_expired_success_is_refreshed(self) -> None:
        cache = FakeCache()
        cache.entries["example.com"] = self.success_entry(
            "example.com",
            fresh_until=self.now - timedelta(seconds=1),
            stale_until=self.now + timedelta(days=1),
        )
        new_date = datetime(2019, 3, 2, tzinfo=UTC)
        service, _, rdap = self.service(
            FakeRdapResult("success", registered_at=new_date),
            cache=cache,
        )

        result = service.lookup("sub.example.com")

        self.assertEqual(result.registered_at, new_date)
        self.assertFalse(result.stale)
        self.assertEqual(rdap.calls, ["example.com"])
        self.assertEqual(cache.success_writes, 1)
        self.assertGreater(cache.prune_calls, 0)

    def test_injected_rng_makes_ttl_jitter_deterministic(self) -> None:
        service, cache, _ = self.service(
            FakeRdapResult(
                "success",
                registered_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )

        service.lookup("example.com")

        entry = cache.entries["example.com"]
        now_epoch = int(self.now.timestamp())
        self.assertEqual(
            entry.fresh_until,
            now_epoch + int(ESTABLISHED_SUCCESS_FRESH_TTL.total_seconds()),
        )
        self.assertEqual(
            entry.stale_until,
            now_epoch + int(ESTABLISHED_SUCCESS_STALE_TTL.total_seconds()),
        )

    def test_success_ttl_adapts_to_domain_age(self) -> None:
        cases = [
            (
                30,
                YOUNG_SUCCESS_FRESH_TTL,
                YOUNG_SUCCESS_STALE_TTL,
            ),
            (
                180,
                RECENT_SUCCESS_FRESH_TTL,
                RECENT_SUCCESS_STALE_TTL,
            ),
            (
                800,
                ESTABLISHED_SUCCESS_FRESH_TTL,
                ESTABLISHED_SUCCESS_STALE_TTL,
            ),
        ]
        now_epoch = int(self.now.timestamp())

        for age_days, fresh_ttl, stale_ttl in cases:
            with self.subTest(age_days=age_days):
                service, cache, _ = self.service(
                    FakeRdapResult(
                        "success",
                        registered_at=self.now - timedelta(days=age_days),
                    )
                )

                service.lookup(f"age-{age_days}.com")

                entry = cache.entries[f"age-{age_days}.com"]
                self.assertEqual(
                    now_epoch + int(fresh_ttl.total_seconds()),
                    entry.fresh_until,
                )
                self.assertEqual(
                    now_epoch + int(stale_ttl.total_seconds()),
                    entry.stale_until,
                )

    def test_stale_success_survives_transient_error_without_overwrite(self) -> None:
        cache = FakeCache()
        old_date = datetime(2018, 4, 5, tzinfo=UTC)
        cache.entries["example.com"] = self.success_entry(
            "example.com",
            registered_at=old_date,
            fresh_until=self.now - timedelta(seconds=1),
            stale_until=self.now + timedelta(days=10),
        )
        retry_after = int((self.now + timedelta(hours=1)).timestamp())
        service, _, rdap = self.service(
            FakeRdapResult(
                "rate_limited",
                error_code="rate_limited",
                retry_after=retry_after,
            ),
            cache=cache,
        )

        first = service.lookup("example.com")
        second = service.lookup("example.com")

        self.assertEqual(first.registered_at, old_date)
        self.assertTrue(first.stale)
        self.assertTrue(second.stale)
        self.assertEqual(len(rdap.calls), 1)
        self.assertEqual(cache.failure_writes, 0)
        self.assertEqual(cache.postpone_calls, 1)
        self.assertEqual(cache.entries["example.com"].status, "success")
        self.assertEqual(cache.entries["example.com"].registered_at, int(old_date.timestamp()))

    def test_rdap_unsupported_falls_back_to_whois(self) -> None:
        whois_calls: list[str] = []
        creation = datetime(2017, 2, 1, tzinfo=UTC)

        def lookup(domain: str):
            whois_calls.append(domain)
            return SimpleNamespace(creation_date=creation)

        service, cache, rdap = self.service(
            FakeRdapResult("unsupported", error_code="unsupported"),
            whois_lookup=lookup,
        )

        result = service.lookup("www.example.com")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.registered_at, creation)
        self.assertEqual(result.source, "whois")
        self.assertEqual(rdap.calls, ["example.com"])
        self.assertEqual(whois_calls, ["example.com"])
        self.assertEqual(cache.success_writes, 1)

    def test_missing_rdap_registration_date_falls_back_to_whois(self) -> None:
        whois_calls: list[str] = []

        def lookup(domain: str):
            whois_calls.append(domain)
            return {"creation_date": datetime(2015, 1, 1, tzinfo=UTC)}

        service, _, _ = self.service(
            FakeRdapResult(
                "missing_registration_date",
                registered_at=None,
                error_code="registration_date_missing",
            ),
            whois_lookup=lookup,
        )

        self.assertEqual(service.lookup("example.com").source, "whois")
        self.assertEqual(whois_calls, ["example.com"])

    def test_whois_is_not_used_for_disallowed_rdap_outcomes(self) -> None:
        cases = [
            FakeRdapResult("not_found", error_code="not_found"),
            FakeRdapResult("rate_limited", error_code="rate_limited"),
            FakeRdapResult("transient_error", error_code="timeout"),
            FakeRdapResult("transient_error", error_code="server_error"),
            FakeRdapResult("parse_error", error_code="domain_mismatch"),
            FakeRdapResult("parse_error", error_code="malformed_response"),
            FakeRdapResult("success", registered_at=None),
        ]

        for rdap_result in cases:
            with self.subTest(rdap_result=rdap_result):
                calls: list[str] = []
                service, _, _ = self.service(
                    rdap_result,
                    whois_lookup=lambda domain: calls.append(domain),
                )
                result = service.lookup("example.com")
                self.assertEqual(calls, [])
                expected = "not_found" if rdap_result.status == "not_found" else "unavailable"
                self.assertEqual(result.status, expected)

    def test_whois_selects_earliest_valid_utc_date(self) -> None:
        earliest = datetime(2010, 2, 3)
        whois_result = SimpleNamespace(
            creation_date=[
                self.now + timedelta(days=2),
                datetime(2018, 1, 1, tzinfo=timezone(timedelta(hours=2))),
                earliest,
                "2012-01-01",
            ]
        )
        service, _, _ = self.service(
            FakeRdapResult("unsupported"),
            whois_lookup=lambda domain: whois_result,
        )

        result = service.lookup("example.com")

        self.assertEqual(result.registered_at, earliest.replace(tzinfo=UTC))

    def test_implausibly_future_dates_are_rejected(self) -> None:
        calls: list[str] = []
        service, _, _ = self.service(
            FakeRdapResult(
                "success",
                registered_at=self.now + timedelta(days=2),
            ),
            whois_lookup=lambda domain: calls.append(domain),
        )

        result = service.lookup("example.com")

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.error_code, "malformed_registration_date")
        self.assertEqual(calls, [])

    def test_registration_dates_before_dns_era_are_rejected(self) -> None:
        calls: list[str] = []
        service, _, _ = self.service(
            FakeRdapResult(
                "success",
                registered_at=datetime(1, 1, 1, tzinfo=UTC),
            ),
            whois_lookup=lambda domain: calls.append(domain),
        )

        result = service.lookup("example.com")

        self.assertEqual("unavailable", result.status)
        self.assertEqual("malformed_registration_date", result.error_code)
        self.assertEqual([], calls)

    def test_normalizes_urls_case_idn_and_multi_label_suffixes(self) -> None:
        cases = [
            ("HTTPS://Login.Example.CO.UK/path", "example.co.uk"),
            ("Sub.Example.COM.", "example.com"),
            ("https://WWW.Żółć.PL/path", "xn--kda4b0koi.pl"),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                service, _, rdap = self.service(
                    FakeRdapResult(
                        "success",
                        registered_at=datetime(2020, 1, 1, tzinfo=UTC),
                    )
                )
                result = service.lookup(value)
                self.assertEqual(result.domain, expected)
                self.assertEqual(rdap.calls, [expected])

    def test_private_and_shared_hosting_are_not_applicable_without_io(self) -> None:
        for value in (
            "paypal.github.io",
            "tenant.vercel.app",
            "paypal.amazonaws.com",
            "localhost",
        ):
            with self.subTest(value=value):
                cache = FakeCache()
                service, _, rdap = self.service(
                    FakeRdapResult("transient_error"),
                    cache=cache,
                )
                result = service.lookup(value)
                self.assertEqual(result.status, "not_applicable")
                self.assertIsNone(result.domain)
                self.assertEqual(cache.get_calls, [])
                self.assertEqual(rdap.calls, [])

    def test_age_progresses_while_registration_date_stays_cached(self) -> None:
        registered_at = self.now - timedelta(days=100, hours=1)
        service, _, rdap = self.service(
            FakeRdapResult("success", registered_at=registered_at)
        )

        first = service.get_domain_age_days("example.com")
        self.clock.advance(timedelta(days=3))
        second = service.get_domain_age_days("example.com")

        self.assertEqual(first, 100)
        self.assertEqual(second, 103)
        self.assertEqual(len(rdap.calls), 1)

    def test_negative_cache_keeps_not_found_distinct(self) -> None:
        service, cache, rdap = self.service(
            FakeRdapResult("not_found", error_code="not_found")
        )

        first = service.lookup("example.com")
        second = service.lookup("sub.example.com")

        self.assertEqual(first.status, "not_found")
        self.assertEqual(second.status, "not_found")
        self.assertEqual(second.error_code, "not_found")
        self.assertEqual(len(rdap.calls), 1)
        self.assertEqual(cache.failure_writes, 1)

    def test_rate_limit_has_granular_negative_cache_but_public_unavailable_status(self) -> None:
        service, cache, rdap = self.service(
            FakeRdapResult("rate_limited", error_code="rdap_rate_limited")
        )

        first = service.lookup("example.com")
        second = service.lookup("example.com")

        self.assertEqual(first.status, "unavailable")
        self.assertEqual(second.status, "unavailable")
        self.assertEqual(cache.entries["example.com"].status, "rate_limited")
        self.assertEqual(len(rdap.calls), 1)

    def test_failure_cache_ttls_are_granular(self) -> None:
        cases = [
            (FakeRdapResult("not_found"), "not_found", NOT_FOUND_TTL),
            (
                FakeRdapResult("transient_error", error_code="timeout"),
                "transient_error",
                TRANSIENT_ERROR_TTL,
            ),
            (
                FakeRdapResult("parse_error", error_code="bad-json"),
                "parse_error",
                PARSE_ERROR_TTL,
            ),
        ]
        now_epoch = int(self.now.timestamp())

        for rdap_result, cache_status, ttl in cases:
            with self.subTest(cache_status=cache_status):
                service, cache, _ = self.service(rdap_result)
                domain = f"{cache_status.replace('_', '-')}.com"
                service.lookup(domain)
                entry = cache.entries[domain]
                self.assertEqual(cache_status, entry.status)
                self.assertEqual(
                    now_epoch + int(ttl.total_seconds()),
                    entry.fresh_until,
                )

        unsupported_service, unsupported_cache, _ = self.service(
            FakeRdapResult("unsupported"),
            whois_lookup=lambda domain: None,
        )
        unsupported_service.lookup("unsupported.com")
        unsupported_entry = unsupported_cache.entries["unsupported.com"]
        self.assertEqual("unsupported", unsupported_entry.status)
        self.assertEqual(
            now_epoch + int(UNSUPPORTED_TTL.total_seconds()),
            unsupported_entry.fresh_until,
        )

    def test_retry_after_is_used_exactly_without_jitter(self) -> None:
        retry_after = int((self.now + timedelta(minutes=17)).timestamp())
        service, cache, _ = self.service(
            FakeRdapResult(
                "rate_limited",
                error_code="rdap_rate_limited",
                retry_after=retry_after,
            )
        )

        service.lookup("example.com")

        entry = cache.entries["example.com"]
        self.assertEqual(retry_after, entry.retry_after)
        self.assertEqual(retry_after, entry.fresh_until)

    def test_retry_after_is_capped_and_honored_for_transient_errors(self) -> None:
        excessive = int((self.now + timedelta(days=30)).timestamp())
        service, cache, _ = self.service(
            FakeRdapResult(
                "transient_error",
                error_code="maintenance",
                retry_after=excessive,
            )
        )

        service.lookup("example.com")

        entry = cache.entries["example.com"]
        expected = int((self.now + timedelta(days=1)).timestamp())
        self.assertEqual(expected, entry.fresh_until)
        self.assertEqual(expected, entry.retry_after)

    def test_whois_not_found_is_cached_as_authoritative_negative(self) -> None:
        class WhoisDomainNotFoundError(Exception):
            pass

        def missing(domain: str):
            raise WhoisDomainNotFoundError(domain)

        service, cache, _ = self.service(
            FakeRdapResult("unsupported"),
            whois_lookup=missing,
        )

        result = service.lookup("example.com")

        self.assertEqual("not_found", result.status)
        self.assertEqual("whois", result.source)
        self.assertEqual("not_found", cache.entries["example.com"].status)

    def test_cache_maintenance_is_throttled_by_time(self) -> None:
        service, cache, _ = self.service(
            FakeRdapResult(
                "success",
                registered_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )

        service.lookup("example.com")
        service.lookup("example.com")
        self.assertEqual(1, cache.prune_calls)

        self.clock.advance(timedelta(hours=6))
        service.lookup("example.com")
        self.assertEqual(2, cache.prune_calls)

    def test_startup_maintenance_runs_before_any_usable_domain_lookup(self) -> None:
        service, cache, rdap = self.service(
            FakeRdapResult(
                "success",
                registered_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )

        service.run_startup_maintenance()
        result = service.lookup("localhost")

        self.assertEqual("not_applicable", result.status)
        self.assertEqual(1, cache.prune_calls)
        self.assertEqual([], rdap.calls)

    def test_single_flight_allows_only_one_upstream_lookup(self) -> None:
        cache = FakeCache()
        rdap = BlockingRdapClient(
            FakeRdapResult(
                "success",
                registered_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        service = DomainRegistrationService(
            cache,
            rdap,
            whois_lookup=lambda domain: None,
            clock=self.clock,
            rng=lambda: 0.5,
        )

        with ThreadPoolExecutor(max_workers=8) as executor:
            first = executor.submit(service.lookup, "www.example.com")
            self.assertTrue(rdap.entered.wait(timeout=2))
            rest = [
                executor.submit(service.lookup, f"s{i}.example.com")
                for i in range(7)
            ]
            rdap.release.set()
            results = [first.result(timeout=2)] + [
                future.result(timeout=2) for future in rest
            ]

        self.assertEqual(len(rdap.calls), 1)
        self.assertTrue(all(result.status == "success" for result in results))

    def test_cache_exceptions_fail_open(self) -> None:
        registered_at = datetime(2020, 1, 1, tzinfo=UTC)
        service, _, rdap = self.service(
            FakeRdapResult("success", registered_at=registered_at),
            cache=ExplodingCache(),
        )

        result = service.lookup("example.com")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.registered_at, registered_at)
        self.assertEqual(rdap.calls, ["example.com"])

    def test_default_whois_lookup_passes_timeout_without_global_socket_mutation(self) -> None:
        sentinel = object()
        fake_module = SimpleNamespace()
        fake_module.whois = unittest.mock.Mock(return_value=sentinel)

        with patch.dict("sys.modules", {"whois": fake_module}):
            result = _default_whois_lookup("example.com")

        self.assertIs(result, sentinel)
        fake_module.whois.assert_called_once_with(
            "example.com",
            timeout=5,
            ignore_socket_errors=False,
        )

    def test_cache_path_environment_is_read_lazily(self) -> None:
        configured = "/tmp/guardian-registration-test.db"

        # domain_registration was imported before this environment mutation.
        with patch.dict("os.environ", {"GUARDIAN_CACHE_DB": configured}):
            self.assertEqual(str(_default_cache_path()), configured)


if __name__ == "__main__":
    unittest.main()
