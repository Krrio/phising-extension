"""Domain registration lookup with persistent caching and safe fallbacks.

The service deliberately keeps network clients and persistence behind small
protocols.  This makes the policy testable without network access and lets the
CLI import without opening (or even choosing) a cache database.
"""

from __future__ import annotations

import os
import random
import threading
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, TypeAlias, cast

from guardian_classic.tools.suspicious_domain_logic import (
    is_shared_hosting_hostname,
    normalize_hostname,
    parse_hostname,
)


RegistrationStatus: TypeAlias = Literal[
    "success",
    "not_found",
    "unavailable",
    "unsupported",
    "not_applicable",
]

CacheFailureStatus: TypeAlias = Literal[
    "not_found",
    "transient_error",
    "parse_error",
    "rate_limited",
    "unsupported",
]

_CACHEABLE_STATUSES = frozenset(
    {
        "success",
        "not_found",
        "transient_error",
        "parse_error",
        "rate_limited",
        "unsupported",
    }
)
PARSER_VERSION = 1
LOCK_STRIPE_COUNT = 64
WHOIS_TIMEOUT_SECONDS = 5
MAX_FUTURE_SKEW = timedelta(hours=24)
MIN_REGISTRATION_DATE = datetime(1980, 1, 1, tzinfo=timezone.utc)
MAX_UPSTREAM_RETRY_AFTER = timedelta(days=1)

# Younger domains change risk category quickly, while an established
# registration date rarely needs refreshing.  ``stale`` is deliberately longer
# than ``fresh`` so a temporary registry outage does not discard a known fact.
YOUNG_DOMAIN_MAX_AGE_DAYS = 90
RECENT_DOMAIN_MAX_AGE_DAYS = 365
YOUNG_SUCCESS_FRESH_TTL = timedelta(days=1)
YOUNG_SUCCESS_STALE_TTL = timedelta(days=7)
RECENT_SUCCESS_FRESH_TTL = timedelta(days=7)
RECENT_SUCCESS_STALE_TTL = timedelta(days=30)
ESTABLISHED_SUCCESS_FRESH_TTL = timedelta(days=30)
ESTABLISHED_SUCCESS_STALE_TTL = timedelta(days=90)

NOT_FOUND_TTL = timedelta(minutes=30)
UNSUPPORTED_TTL = timedelta(days=1)
TRANSIENT_ERROR_TTL = timedelta(minutes=2)
PARSE_ERROR_TTL = timedelta(hours=1)
TTL_JITTER_RATIO = 0.10

CACHE_MAINTENANCE_INTERVAL = timedelta(hours=6)
CACHE_MAINTENANCE_WRITE_INTERVAL = 1_000
CACHE_TOUCH_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class DomainRegistrationResult:
    """Typed outcome of a registration lookup.

    ``stale`` is used only when a previously successful registration date is
    served after its fresh TTL. Negative-cache hits remain explicit statuses.
    """

    domain: str | None
    status: RegistrationStatus
    registered_at: datetime | None = None
    source: str | None = None
    error_code: str | None = None
    stale: bool = False

    def age_days(self, as_of: datetime) -> int | None:
        """Return age derived from ``registered_at``, never from cached age."""
        if self.status != "success" or self.registered_at is None:
            return None

        current = _as_utc_datetime(as_of)
        seconds = (current - self.registered_at).total_seconds()
        # Up to 24 hours of future skew is accepted while parsing upstream
        # dates. It should describe a zero-day-old domain, not a negative age.
        return max(0, int(seconds // 86_400))


class CacheEntryLike(Protocol):
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
    parser_version: int


class DomainRegistrationCacheLike(Protocol):
    def get(self, domain: str) -> CacheEntryLike | None: ...

    def put_success(
        self,
        *,
        domain: str,
        registered_at: int,
        source: str | None,
        fetched_at: int,
        fresh_until: int,
        stale_until: int,
        parser_version: int,
    ) -> None: ...

    def put_failure(
        self,
        *,
        domain: str,
        status: CacheFailureStatus,
        source: str | None,
        fetched_at: int,
        fresh_until: int,
        retry_after: int | None,
        error_code: str | None,
        parser_version: int,
    ) -> None: ...

    def postpone_retry(
        self,
        domain: str,
        *,
        retry_after: int,
        last_accessed_at: int | None = None,
        error_code: str | None = None,
    ) -> bool: ...

    def touch(self, domain: str, *, now: int) -> bool: ...

    def prune(self, *, now: int) -> None: ...

    def maintenance_due(
        self,
        now: int,
        *,
        max_interval_seconds: int,
        max_writes: int,
    ) -> bool: ...


class RdapLookupResultLike(Protocol):
    status: str
    registered_at: datetime | None
    source: str | None
    error_code: str | None
    retry_after: int | None


class RdapClientLike(Protocol):
    def lookup(self, domain: str) -> RdapLookupResultLike: ...


WhoisLookup: TypeAlias = Callable[[str], Any]
Clock: TypeAlias = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _default_whois_lookup(domain: str) -> Any:
    # Import lazily so environments which only serve cached/RDAP results do not
    # pay import cost or fail module import due to optional WHOIS configuration.
    import whois

    return whois.whois(
        domain,
        timeout=WHOIS_TIMEOUT_SECONDS,
        ignore_socket_errors=False,
    )


def _is_whois_not_found_error(error: Exception) -> bool:
    """Recognize python-whois' authoritative negative result.

    Importing the exception lazily keeps the registration module usable when
    WHOIS is not installed in a cache/RDAP-only environment.  The class-name
    fallback also supports injected adapters which expose the same semantic
    error without importing python-whois.
    """
    if error.__class__.__name__ == "WhoisDomainNotFoundError":
        return True

    try:
        from whois.parser import WhoisDomainNotFoundError
    except (ImportError, AttributeError):
        return False
    return isinstance(error, WhoisDomainNotFoundError)


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _datetime_from_epoch(value: int | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _valid_registration_datetime(
    value: object,
    *,
    now: datetime,
    allow_naive: bool,
) -> datetime | None:
    if not isinstance(value, datetime):
        return None

    if (value.tzinfo is None or value.utcoffset() is None) and not allow_naive:
        return None

    normalized = _as_utc_datetime(value)
    if (
        normalized < MIN_REGISTRATION_DATE
        or normalized > now + MAX_FUTURE_SKEW
    ):
        return None
    return normalized


def _extract_whois_registration_date(
    response: object,
    *,
    now: datetime,
) -> datetime | None:
    if isinstance(response, dict):
        creation_date = response.get("creation_date")
    else:
        creation_date = getattr(response, "creation_date", None)

    values: list[object]
    if isinstance(creation_date, (list, tuple, set)):
        values = list(creation_date)
    else:
        values = [creation_date]

    valid_dates = [
        valid
        for value in values
        if (
            valid := _valid_registration_datetime(
                value,
                now=now,
                allow_naive=True,
            )
        )
        is not None
    ]
    return min(valid_dates, default=None)


@dataclass(frozen=True, slots=True)
class _ResolvedUpstream:
    status: Literal["success", "not_found", "unavailable", "unsupported"]
    cache_status: CacheFailureStatus | None
    registered_at: datetime | None
    source: str | None
    error_code: str | None
    retry_after: int | None


class DomainRegistrationService:
    """Resolve registration dates with RDAP-first, bounded single-flight I/O."""

    def __init__(
        self,
        cache: DomainRegistrationCacheLike,
        rdap_client: RdapClientLike,
        whois_lookup: WhoisLookup | None = None,
        clock: Clock | None = None,
        rng: random.Random | Callable[[], float] | None = None,
    ) -> None:
        self._cache = cache
        self._rdap_client = rdap_client
        self._whois_lookup = whois_lookup or _default_whois_lookup
        self._clock = clock or _default_clock
        self._rng = rng or random.Random()
        self._locks = tuple(threading.Lock() for _ in range(LOCK_STRIPE_COUNT))
        self._maintenance_lock = threading.Lock()
        self._maintenance_running = False
        self._last_prune_at: int | None = None
        self._writes_since_prune = 0

    def run_startup_maintenance(self) -> None:
        """Run fail-open cache cleanup once when the process service starts."""

        now_epoch = int(self._now().timestamp())
        self._maybe_prune(now_epoch, force=True)

    def lookup(self, value: str) -> DomainRegistrationResult:
        """Look up the ICANN registrable domain represented by ``value``."""
        domain = self._normalize_registrable_domain(value)
        if domain is None:
            return DomainRegistrationResult(domain=None, status="not_applicable")

        now = self._now()
        now_epoch = int(now.timestamp())
        self._maybe_prune(now_epoch)
        cached = self._safe_cache_get(domain)
        immediate = self._usable_cache_result(cached, now_epoch=now_epoch)
        if immediate is not None:
            self._safe_touch(cached, now_epoch)
            return immediate

        lock = self._locks[zlib.crc32(domain.encode("ascii")) % len(self._locks)]
        with lock:
            # Another caller sharing this exact domain may have populated the
            # cache while this caller waited for the stripe.
            now = self._now()
            now_epoch = int(now.timestamp())
            cached = self._safe_cache_get(domain)
            immediate = self._usable_cache_result(cached, now_epoch=now_epoch)
            if immediate is not None:
                self._safe_touch(cached, now_epoch)
                return immediate

            stale_success = self._stale_success_result(
                cached,
                now_epoch=now_epoch,
            )
            resolved = self._resolve_upstream(domain, now=now)

            if resolved.status == "success" and resolved.registered_at is not None:
                result = DomainRegistrationResult(
                    domain=domain,
                    status="success",
                    registered_at=resolved.registered_at,
                    source=resolved.source,
                )
                self._safe_put_success(result, now_epoch=now_epoch)
                return result

            cache_status = resolved.cache_status or "parse_error"
            refresh_after = self._next_refresh_at(
                now_epoch=now_epoch,
                cache_status=cache_status,
                upstream_retry_after=resolved.retry_after,
            )

            # A known registration date is stronger than a registry error or a
            # response which temporarily lacks a usable date.  An authoritative
            # not-found result is intentionally excluded: the domain may have
            # expired and the old registration should no longer be presented as
            # current evidence.
            if stale_success is not None and resolved.status in {
                "unavailable",
                "unsupported",
            }:
                self._safe_postpone_retry(
                    domain,
                    retry_after=refresh_after,
                    now_epoch=now_epoch,
                    error_code=resolved.error_code,
                )
                return stale_success

            result = DomainRegistrationResult(
                domain=domain,
                status=resolved.status,
                source=resolved.source,
                error_code=resolved.error_code,
            )
            self._safe_put_failure(
                result,
                cache_status=cache_status,
                now_epoch=now_epoch,
                fresh_until=refresh_after,
                retry_after=(
                    refresh_after
                    if cache_status in {"transient_error", "rate_limited"}
                    else None
                ),
            )
            return result

    # A descriptive alias keeps integrations readable while ``lookup`` mirrors
    # the upstream client's vocabulary.
    get_registration = lookup

    def get_domain_age_days(self, value: str) -> int | None:
        result = self.lookup(value)
        return result.age_days(self._now())

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")
        return _as_utc_datetime(value)

    @staticmethod
    def _normalize_registrable_domain(value: str) -> str | None:
        hostname = normalize_hostname(value)
        if not hostname:
            return None

        parsed = parse_hostname(hostname)
        if (
            parsed is None
            or not parsed.is_icann
            or parsed.is_private
            or is_shared_hosting_hostname(hostname)
        ):
            return None

        return parsed.domain.lower()

    def _resolve_upstream(
        self,
        domain: str,
        *,
        now: datetime,
    ) -> _ResolvedUpstream:
        try:
            rdap = self._rdap_client.lookup(domain)
        except Exception:
            return _ResolvedUpstream(
                status="unavailable",
                cache_status="transient_error",
                registered_at=None,
                source="rdap",
                error_code="network_error",
                retry_after=None,
            )

        status = str(getattr(rdap, "status", "unavailable"))
        source = getattr(rdap, "source", None) or "rdap"
        error_code = getattr(rdap, "error_code", None)
        retry_after = getattr(rdap, "retry_after", None)

        if status == "success":
            raw_registered_at = getattr(rdap, "registered_at", None)
            registered_at = _valid_registration_datetime(
                raw_registered_at,
                now=now,
                allow_naive=False,
            )
            if registered_at is not None:
                return _ResolvedUpstream(
                    status="success",
                    cache_status=None,
                    registered_at=registered_at,
                    source=source,
                    error_code=None,
                    retry_after=None,
                )

            if raw_registered_at is not None:
                # A malformed or implausibly future RDAP date must not be
                # laundered through WHOIS fallback.
                return _ResolvedUpstream(
                    status="unavailable",
                    cache_status="parse_error",
                    registered_at=None,
                    source=source,
                    error_code=error_code or "malformed_registration_date",
                    retry_after=retry_after,
                )

            # The RDAP client has an explicit ``missing_registration_date``
            # status. A nominal success without a date is malformed and must
            # not silently broaden the narrowly defined WHOIS fallback policy.
            return _ResolvedUpstream(
                status="unavailable",
                cache_status="parse_error",
                registered_at=None,
                source=source,
                error_code=error_code or "malformed_registration_date",
                retry_after=None,
            )

        if status == "not_found":
            return _ResolvedUpstream(
                status="not_found",
                cache_status="not_found",
                registered_at=None,
                source=source,
                error_code=error_code or "not_found",
                retry_after=None,
            )

        if status in {"unsupported", "missing_registration_date"}:
            return self._resolve_whois(domain, now=now)

        if status in {"transient_error", "rate_limited", "unavailable"}:
            return _ResolvedUpstream(
                status="unavailable",
                cache_status=(
                    "rate_limited" if status == "rate_limited" else "transient_error"
                ),
                registered_at=None,
                source=source,
                error_code=error_code or "unavailable",
                retry_after=retry_after,
            )

        if status == "parse_error":
            return _ResolvedUpstream(
                status="unavailable",
                cache_status="parse_error",
                registered_at=None,
                source=source,
                error_code=error_code or "parse_error",
                retry_after=None,
            )

        return _ResolvedUpstream(
            status="unavailable",
            cache_status="parse_error",
            registered_at=None,
            source=source,
            error_code="invalid_rdap_status",
            retry_after=None,
        )

    def _resolve_whois(
        self,
        domain: str,
        *,
        now: datetime,
    ) -> _ResolvedUpstream:
        try:
            response = self._whois_lookup(domain)
        except Exception as error:
            if _is_whois_not_found_error(error):
                return _ResolvedUpstream(
                    status="not_found",
                    cache_status="not_found",
                    registered_at=None,
                    source="whois",
                    error_code="not_found",
                    retry_after=None,
                )
            return _ResolvedUpstream(
                status="unavailable",
                cache_status="transient_error",
                registered_at=None,
                source="whois",
                error_code="whois_error",
                retry_after=None,
            )

        registered_at = _extract_whois_registration_date(response, now=now)
        if registered_at is None:
            return _ResolvedUpstream(
                status="unsupported",
                cache_status="unsupported",
                registered_at=None,
                source="whois",
                error_code="missing_registration_date",
                retry_after=None,
            )

        return _ResolvedUpstream(
            status="success",
            cache_status=None,
            registered_at=registered_at,
            source="whois",
            error_code=None,
            retry_after=None,
        )

    def _usable_cache_result(
        self,
        entry: CacheEntryLike | None,
        *,
        now_epoch: int,
    ) -> DomainRegistrationResult | None:
        if entry is None or getattr(entry, "parser_version", None) != PARSER_VERSION:
            return None

        status = getattr(entry, "status", None)
        if status not in _CACHEABLE_STATUSES:
            return None

        if now_epoch < entry.fresh_until:
            return self._result_from_cache(entry, stale=False)

        retry_after = getattr(entry, "retry_after", None)
        if retry_after is not None and now_epoch < retry_after:
            if status == "success":
                return self._stale_success_result(entry, now_epoch=now_epoch)
            return self._result_from_cache(entry, stale=False)

        return None

    def _stale_success_result(
        self,
        entry: CacheEntryLike | None,
        *,
        now_epoch: int,
    ) -> DomainRegistrationResult | None:
        if (
            entry is None
            or getattr(entry, "parser_version", None) != PARSER_VERSION
            or getattr(entry, "status", None) != "success"
            or getattr(entry, "registered_at", None) is None
            or getattr(entry, "stale_until", None) is None
            or now_epoch >= cast(int, entry.stale_until)
        ):
            return None

        return self._result_from_cache(entry, stale=True)

    @staticmethod
    def _result_from_cache(
        entry: CacheEntryLike,
        *,
        stale: bool,
    ) -> DomainRegistrationResult | None:
        cached_status = entry.status
        status: RegistrationStatus
        if cached_status in {"transient_error", "parse_error", "rate_limited"}:
            status = "unavailable"
        else:
            status = cast(RegistrationStatus, cached_status)
        registered_at = _datetime_from_epoch(entry.registered_at)
        if status == "success" and registered_at is None:
            return None

        return DomainRegistrationResult(
            domain=entry.domain,
            status=status,
            registered_at=registered_at,
            source=entry.source,
            error_code=entry.error_code,
            stale=stale,
        )

    def _jittered_seconds(self, duration: timedelta) -> int:
        base = duration.total_seconds()
        rng = self._rng
        if hasattr(rng, "uniform"):
            factor = cast(random.Random, rng).uniform(
                1.0 - TTL_JITTER_RATIO,
                1.0 + TTL_JITTER_RATIO,
            )
        else:
            unit = float(cast(Callable[[], float], rng)())
            # Callable RNGs use the conventional [0, 1] range. Clamp hostile or
            # accidentally out-of-range fakes so TTLs remain bounded.
            unit = min(1.0, max(0.0, unit))
            factor = 1.0 - TTL_JITTER_RATIO + (2 * TTL_JITTER_RATIO * unit)
        return max(1, int(round(base * factor)))

    def _next_refresh_at(
        self,
        *,
        now_epoch: int,
        cache_status: CacheFailureStatus,
        upstream_retry_after: int | None,
    ) -> int:
        # Retry-After is an authoritative instruction and therefore is not
        # jittered or extended.  If it is absent/invalid, use the ordinary
        # short transient-error TTL.
        if (
            cache_status in {"rate_limited", "transient_error"}
            and isinstance(upstream_retry_after, int)
            and upstream_retry_after > now_epoch
        ):
            maximum = now_epoch + int(MAX_UPSTREAM_RETRY_AFTER.total_seconds())
            return min(upstream_retry_after, maximum)
        return now_epoch + self._jittered_seconds(
            self._failure_ttl(cache_status)
        )

    @staticmethod
    def _failure_ttl(status: CacheFailureStatus) -> timedelta:
        if status == "not_found":
            return NOT_FOUND_TTL
        if status == "unsupported":
            return UNSUPPORTED_TTL
        if status == "parse_error":
            return PARSE_ERROR_TTL
        return TRANSIENT_ERROR_TTL

    @staticmethod
    def _success_ttls(
        registered_at: datetime,
        *,
        now_epoch: int,
    ) -> tuple[timedelta, timedelta]:
        registered_epoch = int(registered_at.timestamp())
        age_days = max(0, (now_epoch - registered_epoch) // 86_400)
        if age_days < YOUNG_DOMAIN_MAX_AGE_DAYS:
            return YOUNG_SUCCESS_FRESH_TTL, YOUNG_SUCCESS_STALE_TTL
        if age_days < RECENT_DOMAIN_MAX_AGE_DAYS:
            return RECENT_SUCCESS_FRESH_TTL, RECENT_SUCCESS_STALE_TTL
        return ESTABLISHED_SUCCESS_FRESH_TTL, ESTABLISHED_SUCCESS_STALE_TTL

    def _safe_cache_get(self, domain: str) -> CacheEntryLike | None:
        try:
            return self._cache.get(domain)
        except Exception:
            return None

    def _safe_touch(self, entry: CacheEntryLike | None, now_epoch: int) -> None:
        if entry is None:
            return
        if now_epoch - entry.last_accessed_at < int(
            CACHE_TOUCH_INTERVAL.total_seconds()
        ):
            return
        try:
            changed = self._cache.touch(entry.domain, now=now_epoch)
        except Exception:
            return
        if changed:
            self._record_cache_write(now_epoch)

    def _safe_put_success(
        self,
        result: DomainRegistrationResult,
        *,
        now_epoch: int,
    ) -> None:
        assert result.domain is not None
        assert result.registered_at is not None
        fresh_ttl, stale_ttl = self._success_ttls(
            result.registered_at,
            now_epoch=now_epoch,
        )
        fresh_until = now_epoch + self._jittered_seconds(fresh_ttl)
        stale_until = now_epoch + self._jittered_seconds(stale_ttl)
        try:
            self._cache.put_success(
                domain=result.domain,
                registered_at=int(result.registered_at.timestamp()),
                source=result.source,
                fetched_at=now_epoch,
                fresh_until=fresh_until,
                stale_until=max(stale_until, fresh_until + 1),
                parser_version=PARSER_VERSION,
            )
        except Exception:
            return
        self._record_cache_write(now_epoch)

    def _safe_put_failure(
        self,
        result: DomainRegistrationResult,
        *,
        cache_status: CacheFailureStatus,
        now_epoch: int,
        fresh_until: int,
        retry_after: int | None,
    ) -> None:
        assert result.domain is not None
        try:
            self._cache.put_failure(
                domain=result.domain,
                status=cache_status,
                source=result.source,
                fetched_at=now_epoch,
                fresh_until=fresh_until,
                retry_after=retry_after,
                error_code=result.error_code,
                parser_version=PARSER_VERSION,
            )
        except Exception:
            return
        self._record_cache_write(now_epoch)

    def _safe_postpone_retry(
        self,
        domain: str,
        *,
        retry_after: int,
        now_epoch: int,
        error_code: str | None,
    ) -> None:
        try:
            changed = self._cache.postpone_retry(
                domain,
                retry_after=retry_after,
                last_accessed_at=now_epoch,
                error_code=error_code,
            )
        except Exception:
            return
        if changed:
            self._record_cache_write(now_epoch)

    def _record_cache_write(self, now_epoch: int) -> None:
        self._maybe_prune(now_epoch, record_write=True)

    def _maybe_prune(
        self,
        now_epoch: int,
        *,
        record_write: bool = False,
        force: bool = False,
    ) -> None:
        interval_seconds = int(CACHE_MAINTENANCE_INTERVAL.total_seconds())
        persistent_due = False
        if record_write:
            try:
                persistent_due = self._cache.maintenance_due(
                    now_epoch,
                    max_interval_seconds=interval_seconds,
                    max_writes=CACHE_MAINTENANCE_WRITE_INTERVAL,
                )
            except Exception:
                persistent_due = False

        with self._maintenance_lock:
            if record_write:
                self._writes_since_prune += 1

            local_due = (
                force
                or self._last_prune_at is None
                or now_epoch - self._last_prune_at >= interval_seconds
                or self._writes_since_prune
                >= CACHE_MAINTENANCE_WRITE_INTERVAL
            )
            if self._maintenance_running or not (local_due or persistent_due):
                return

            # Reserve the maintenance slot before touching SQLite so concurrent
            # request threads do not all start the same cleanup. Counters are
            # committed only after successful maintenance, so a failure is
            # retried by the next lookup instead of waiting another six hours.
            self._maintenance_running = True
            claimed_writes = self._writes_since_prune

        succeeded = False
        try:
            self._cache.prune(now=now_epoch)
            succeeded = True
        except Exception:
            pass
        finally:
            with self._maintenance_lock:
                self._maintenance_running = False
                if succeeded:
                    self._last_prune_at = now_epoch
                    self._writes_since_prune = max(
                        0,
                        self._writes_since_prune - claimed_writes,
                    )


_default_service: DomainRegistrationService | None = None
_default_service_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class _MemoryBootstrapEntry:
    payload: str
    fetched_at: int
    fresh_until: int
    etag: str | None
    last_modified: str | None


class _UnavailableCache:
    """Fail-open domain cache with a small in-memory RDAP bootstrap cache."""

    def __init__(self) -> None:
        self._bootstrap: _MemoryBootstrapEntry | None = None
        self._endpoint_backoffs: dict[str, tuple[int, int]] = {}
        self._bootstrap_lock = threading.Lock()

    def get_bootstrap(self) -> _MemoryBootstrapEntry | None:
        with self._bootstrap_lock:
            return self._bootstrap

    def put_bootstrap(
        self,
        payload: str,
        fetched_at: int,
        fresh_until: int,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        with self._bootstrap_lock:
            if (
                self._bootstrap is not None
                and fetched_at < self._bootstrap.fetched_at
            ):
                return
            self._bootstrap = _MemoryBootstrapEntry(
                payload=payload,
                fetched_at=fetched_at,
                fresh_until=fresh_until,
                etag=etag,
                last_modified=last_modified,
            )

    def get_endpoint_backoff(self, endpoint: str) -> int | None:
        with self._bootstrap_lock:
            stored = self._endpoint_backoffs.get(endpoint.rstrip("/"))
            return None if stored is None else stored[0]

    def put_endpoint_backoff(
        self,
        endpoint: str,
        retry_after: int,
        observed_at: int,
    ) -> None:
        normalized = endpoint.rstrip("/")
        with self._bootstrap_lock:
            stored = self._endpoint_backoffs.get(normalized)
            if stored is not None:
                retry_after = max(retry_after, stored[0])
                observed_at = max(observed_at, stored[1])
            self._endpoint_backoffs[normalized] = (retry_after, observed_at)

    def maintenance_due(
        self,
        now: int,
        *,
        max_interval_seconds: int,
        max_writes: int,
    ) -> bool:
        del now, max_interval_seconds, max_writes
        return False

    def prune(self, *, now: int) -> int:
        del now
        return 0

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"cache is unavailable: {name}")


def _default_cache_path() -> Path:
    configured = os.environ.get("GUARDIAN_CACHE_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / ".cache" / "registration_cache.db"


def get_default_service() -> DomainRegistrationService:
    """Create the process-wide service lazily, reading its path only now."""
    global _default_service

    if _default_service is not None:
        return _default_service

    with _default_service_lock:
        if _default_service is None:
            from guardian_classic.domain_cache import DomainRegistrationCache
            from guardian_classic.rdap_client import RdapClient

            try:
                cache: Any = DomainRegistrationCache(_default_cache_path())
            except Exception:
                # A read-only filesystem or corrupt cache must not disable
                # registration checks; RDAP and WHOIS remain usable in-memory.
                cache = _UnavailableCache()
            service = DomainRegistrationService(
                cache=cache,
                rdap_client=RdapClient(cache),
            )
            service.run_startup_maintenance()
            _default_service = service
    return _default_service


def get_domain_registration(value: str) -> DomainRegistrationResult:
    """Convenience API backed by the lazily constructed default service."""
    return get_default_service().lookup(value)
