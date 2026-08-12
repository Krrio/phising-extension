"""Persistent SQLite cache for domain-registration and RDAP bootstrap data."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias

import idna


CacheStatus: TypeAlias = Literal[
    "success",
    "not_found",
    "transient_error",
    "parse_error",
    "rate_limited",
    "unsupported",
]
FailureStatus: TypeAlias = Literal[
    "not_found",
    "transient_error",
    "parse_error",
    "rate_limited",
    "unsupported",
]


@dataclass(frozen=True, slots=True)
class CacheEntry:
    domain: str
    status: CacheStatus
    registered_at: int | None
    source: str | None
    fetched_at: int
    fresh_until: int
    stale_until: int | None
    retry_after: int | None
    last_accessed_at: int
    error_code: str | None
    parser_version: int


@dataclass(frozen=True, slots=True)
class BootstrapCacheEntry:
    payload: str
    fetched_at: int
    fresh_until: int
    etag: str | None
    last_modified: str | None


_SCHEMA_VERSION: Final = 3
_SQLITE_TIMEOUT_SECONDS: Final = 5.0
_BUSY_TIMEOUT_MILLISECONDS: Final = 5_000
_DEFAULT_TOUCH_INTERVAL_SECONDS: Final = 3_600
_DEFAULT_MAX_ENTRIES: Final = 50_000
_DEFAULT_MAX_BYTES: Final = 64 * 1024 * 1024
_DEFAULT_TARGET_RATIO: Final = 0.80
_FAILURE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "not_found",
        "transient_error",
        "parse_error",
        "rate_limited",
        "unsupported",
    }
)

_CREATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS domain_cache (
    domain TEXT PRIMARY KEY NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'success',
            'not_found',
            'transient_error',
            'parse_error',
            'rate_limited',
            'unsupported'
        )
    ),
    registered_at INTEGER,
    source TEXT,
    fetched_at INTEGER NOT NULL,
    fresh_until INTEGER NOT NULL,
    stale_until INTEGER,
    retry_after INTEGER,
    last_accessed_at INTEGER NOT NULL,
    error_code TEXT,
    parser_version INTEGER NOT NULL,
    CHECK (
        (
            status = 'success'
            AND registered_at IS NOT NULL
            AND stale_until IS NOT NULL
        )
        OR
        (
            status <> 'success'
            AND registered_at IS NULL
            AND stale_until IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS domain_cache_expiration_idx
    ON domain_cache(status, fresh_until, stale_until);

CREATE INDEX IF NOT EXISTS domain_cache_lru_idx
    ON domain_cache(last_accessed_at, domain);

CREATE TABLE IF NOT EXISTS rdap_bootstrap_cache (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    payload TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    fresh_until INTEGER NOT NULL,
    etag TEXT,
    last_modified TEXT
);

CREATE TABLE IF NOT EXISTS rdap_endpoint_backoff (
    endpoint TEXT PRIMARY KEY NOT NULL,
    retry_after INTEGER NOT NULL,
    observed_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS rdap_endpoint_backoff_expiration_idx
    ON rdap_endpoint_backoff(retry_after);

CREATE TABLE IF NOT EXISTS cache_maintenance (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    write_sequence INTEGER NOT NULL DEFAULT 0,
    pruned_through INTEGER NOT NULL DEFAULT 0,
    last_pruned_at INTEGER
);

INSERT OR IGNORE INTO cache_maintenance (
    singleton_id, write_sequence, pruned_through, last_pruned_at
) VALUES (1, 0, 0, NULL);
"""

_MIGRATE_V1_TO_V2_SQL = """
CREATE TABLE IF NOT EXISTS rdap_endpoint_backoff (
    endpoint TEXT PRIMARY KEY NOT NULL,
    retry_after INTEGER NOT NULL,
    observed_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS rdap_endpoint_backoff_expiration_idx
    ON rdap_endpoint_backoff(retry_after);
"""

_MIGRATE_V2_TO_V3_SQL = """
CREATE TABLE IF NOT EXISTS cache_maintenance (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    write_sequence INTEGER NOT NULL DEFAULT 0,
    pruned_through INTEGER NOT NULL DEFAULT 0,
    last_pruned_at INTEGER
);

INSERT OR IGNORE INTO cache_maintenance (
    singleton_id, write_sequence, pruned_through, last_pruned_at
) VALUES (1, 0, 0, NULL);
"""


class DomainRegistrationCache:
    """Small process-safe cache backed by one SQLite database file.

    A fresh connection is opened for every public operation. SQLite serializes
    the short write transactions, while readers do not share connection state
    across FastAPI worker threads.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=_SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MILLISECONDS}")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            journal_mode = str(
                connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
            ).lower()
            if journal_mode != "delete":
                raise RuntimeError(
                    "Domain cache requires SQLite DELETE journal mode."
                )

            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > _SCHEMA_VERSION:
                raise RuntimeError(
                    "Domain cache schema is newer than this application "
                    f"(database={version}, supported={_SCHEMA_VERSION})."
                )

            if version == 0:
                # This must be selected before the first table is created.
                connection.execute("PRAGMA auto_vacuum = INCREMENTAL")

            connection.execute("BEGIN IMMEDIATE")
            try:
                # Another process may have initialized the database while this
                # connection was waiting for the write lock.
                version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                if version > _SCHEMA_VERSION:
                    raise RuntimeError(
                        "Domain cache schema is newer than this application "
                        f"(database={version}, supported={_SCHEMA_VERSION})."
                    )

                if version == 0:
                    for statement in _CREATE_SCHEMA_SQL.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    self._verify_schema(connection)
                    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                elif version == 1:
                    for statement in _MIGRATE_V1_TO_V2_SQL.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    for statement in _MIGRATE_V2_TO_V3_SQL.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    self._verify_schema(connection)
                    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                elif version == 2:
                    for statement in _MIGRATE_V2_TO_V3_SQL.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    self._verify_schema(connection)
                    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                elif version == _SCHEMA_VERSION:
                    self._verify_schema(connection)

                connection.commit()
            except BaseException:
                connection.rollback()
                raise

            self._verify_schema(connection)
        finally:
            connection.close()

    @staticmethod
    def _verify_schema(connection: sqlite3.Connection) -> None:
        expected_columns = {
            "domain",
            "status",
            "registered_at",
            "source",
            "fetched_at",
            "fresh_until",
            "stale_until",
            "retry_after",
            "last_accessed_at",
            "error_code",
            "parser_version",
        }
        actual_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(domain_cache)")
        }
        if actual_columns != expected_columns:
            raise RuntimeError("Domain cache schema is missing or incompatible.")

        bootstrap_columns = {
            "singleton_id",
            "payload",
            "fetched_at",
            "fresh_until",
            "etag",
            "last_modified",
        }
        actual_bootstrap_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(rdap_bootstrap_cache)")
        }
        if actual_bootstrap_columns != bootstrap_columns:
            raise RuntimeError(
                "RDAP bootstrap cache schema is missing or incompatible."
            )

        backoff_columns = {"endpoint", "retry_after", "observed_at"}
        actual_backoff_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(rdap_endpoint_backoff)")
        }
        if actual_backoff_columns != backoff_columns:
            raise RuntimeError(
                "RDAP endpoint-backoff schema is missing or incompatible."
            )

        maintenance_columns = {
            "singleton_id",
            "write_sequence",
            "pruned_through",
            "last_pruned_at",
        }
        actual_maintenance_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(cache_maintenance)")
        }
        if actual_maintenance_columns != maintenance_columns:
            raise RuntimeError(
                "Domain-cache maintenance schema is missing or incompatible."
            )
        maintenance_rows = int(
            connection.execute(
                "SELECT COUNT(*) FROM cache_maintenance WHERE singleton_id = 1"
            ).fetchone()[0]
        )
        if maintenance_rows != 1:
            raise RuntimeError("Domain-cache maintenance state is missing.")

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        normalized = domain.strip().lower().rstrip(".")
        if not normalized:
            raise ValueError("domain must not be empty")

        try:
            return idna.encode(
                normalized,
                uts46=True,
                std3_rules=True,
            ).decode("ascii")
        except idna.IDNAError as error:
            raise ValueError("domain is not valid IDNA") from error

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> CacheEntry:
        return CacheEntry(
            domain=row["domain"],
            status=row["status"],
            registered_at=row["registered_at"],
            source=row["source"],
            fetched_at=row["fetched_at"],
            fresh_until=row["fresh_until"],
            stale_until=row["stale_until"],
            retry_after=row["retry_after"],
            last_accessed_at=row["last_accessed_at"],
            error_code=row["error_code"],
            parser_version=row["parser_version"],
        )

    def get(self, domain: str) -> CacheEntry | None:
        normalized_domain = self._normalize_domain(domain)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM domain_cache WHERE domain = ?",
                (normalized_domain,),
            ).fetchone()
            return None if row is None else self._entry_from_row(row)
        finally:
            connection.close()

    def put_success(
        self,
        domain: str,
        registered_at: int,
        source: str | None,
        fetched_at: int,
        fresh_until: int,
        stale_until: int,
        parser_version: int,
    ) -> None:
        normalized_domain = self._normalize_domain(domain)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO domain_cache (
                    domain, status, registered_at, source, fetched_at,
                    fresh_until, stale_until, retry_after, last_accessed_at,
                    error_code, parser_version
                ) VALUES (?, 'success', ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    status = excluded.status,
                    registered_at = excluded.registered_at,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    fresh_until = excluded.fresh_until,
                    stale_until = excluded.stale_until,
                    retry_after = NULL,
                    last_accessed_at = excluded.last_accessed_at,
                    error_code = NULL,
                    parser_version = excluded.parser_version
                WHERE excluded.fetched_at >= domain_cache.fetched_at
                """,
                (
                    normalized_domain,
                    registered_at,
                    source,
                    fetched_at,
                    fresh_until,
                    stale_until,
                    fetched_at,
                    parser_version,
                ),
            )
            if cursor.rowcount > 0:
                self._record_write_with_connection(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def put_failure(
        self,
        domain: str,
        status: FailureStatus,
        source: str | None,
        fetched_at: int,
        fresh_until: int,
        retry_after: int | None = None,
        error_code: str | None = None,
        parser_version: int = 1,
    ) -> None:
        if status not in _FAILURE_STATUSES:
            raise ValueError(f"invalid failure cache status: {status}")

        normalized_domain = self._normalize_domain(domain)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO domain_cache (
                    domain, status, registered_at, source, fetched_at,
                    fresh_until, stale_until, retry_after, last_accessed_at,
                    error_code, parser_version
                ) VALUES (?, ?, NULL, ?, ?, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    status = excluded.status,
                    registered_at = NULL,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    fresh_until = excluded.fresh_until,
                    stale_until = NULL,
                    retry_after = excluded.retry_after,
                    last_accessed_at = excluded.last_accessed_at,
                    error_code = excluded.error_code,
                    parser_version = excluded.parser_version
                WHERE
                    (
                        excluded.fetched_at > domain_cache.fetched_at
                        OR (
                            excluded.fetched_at = domain_cache.fetched_at
                            AND domain_cache.status <> 'success'
                            AND (
                                excluded.status = 'not_found'
                                OR domain_cache.status <> 'not_found'
                            )
                        )
                    )
                    AND (
                        domain_cache.status NOT IN ('success', 'not_found')
                        OR (
                            domain_cache.status = 'success'
                            AND (
                                (
                                    excluded.status = 'not_found'
                                    AND excluded.fetched_at
                                        > domain_cache.fetched_at
                                )
                                OR domain_cache.stale_until
                                    <= excluded.fetched_at
                            )
                        )
                        OR (
                            domain_cache.status = 'not_found'
                            AND (
                                excluded.status = 'not_found'
                                OR domain_cache.fresh_until
                                    <= excluded.fetched_at
                            )
                        )
                    )
                """,
                (
                    normalized_domain,
                    status,
                    source,
                    fetched_at,
                    fresh_until,
                    retry_after,
                    fetched_at,
                    error_code,
                    parser_version,
                ),
            )
            if cursor.rowcount > 0:
                self._record_write_with_connection(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def postpone_retry(
        self,
        domain: str,
        retry_after: int,
        error_code: str | None = None,
        *,
        last_accessed_at: int | None = None,
    ) -> bool:
        """Delay refresh of an existing success without losing stale data."""

        normalized_domain = self._normalize_domain(domain)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if last_accessed_at is None:
                cursor = connection.execute(
                    """
                    UPDATE domain_cache
                    SET retry_after = MAX(COALESCE(retry_after, ?), ?),
                        error_code = ?
                    WHERE domain = ? AND status = 'success'
                    """,
                    (retry_after, retry_after, error_code, normalized_domain),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE domain_cache
                    SET retry_after = MAX(COALESCE(retry_after, ?), ?),
                        error_code = ?,
                        last_accessed_at = MAX(last_accessed_at, ?)
                    WHERE domain = ?
                        AND status = 'success'
                        AND stale_until > ?
                        AND fetched_at <= ?
                    """,
                    (
                        retry_after,
                        retry_after,
                        error_code,
                        last_accessed_at,
                        normalized_domain,
                        last_accessed_at,
                        last_accessed_at,
                    ),
                )
            changed = cursor.rowcount > 0
            if changed:
                self._record_write_with_connection(connection)
            connection.commit()
            return changed
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def touch(
        self,
        domain: str,
        now: int,
        min_interval: int = _DEFAULT_TOUCH_INTERVAL_SECONDS,
    ) -> bool:
        """Coarsely update LRU time to avoid a write for every cache hit."""

        if min_interval < 0:
            raise ValueError("min_interval must be non-negative")

        normalized_domain = self._normalize_domain(domain)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE domain_cache
                SET last_accessed_at = ?
                WHERE domain = ? AND last_accessed_at <= ?
                """,
                (now, normalized_domain, now - min_interval),
            )
            changed = cursor.rowcount > 0
            if changed:
                self._record_write_with_connection(connection)
            connection.commit()
            return changed
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def prune(
        self,
        now: int,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        target_ratio: float = _DEFAULT_TARGET_RATIO,
        batch_size: int = 500,
    ) -> int:
        """Remove expired rows and enforce count/disk LRU watermarks.

        ``max_entries`` applies to domain results. ``max_bytes`` applies to the
        complete SQLite file, including RDAP bootstrap and endpoint backoff
        rows. Auxiliary rows are cheaper to recreate, so size-only eviction
        removes them before live domain results.
        """

        if max_entries < 0:
            raise ValueError("max_entries must be non-negative")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if not 0 < target_ratio <= 1:
            raise ValueError("target_ratio must be in (0, 1]")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        deleted = 0
        connection = self._connect()
        try:
            prune_through = int(
                connection.execute(
                    """
                    SELECT write_sequence
                    FROM cache_maintenance
                    WHERE singleton_id = 1
                    """
                ).fetchone()[0]
            )

            while True:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    cursor = connection.execute(
                        """
                        DELETE FROM domain_cache
                        WHERE domain IN (
                            SELECT domain
                            FROM domain_cache
                            WHERE
                                (status = 'success' AND stale_until <= ?)
                                OR
                                (status <> 'success' AND fresh_until <= ?)
                            ORDER BY
                                CASE WHEN status = 'success'
                                    THEN stale_until ELSE fresh_until END,
                                domain
                            LIMIT ?
                        )
                        """,
                        (now, now, batch_size),
                    )
                    removed = cursor.rowcount
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

                deleted += removed
                if removed < batch_size:
                    break

            while True:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    cursor = connection.execute(
                        """
                        DELETE FROM rdap_endpoint_backoff
                        WHERE endpoint IN (
                            SELECT endpoint
                            FROM rdap_endpoint_backoff
                            WHERE retry_after <= ?
                            ORDER BY retry_after, endpoint
                            LIMIT ?
                        )
                        """,
                        (now, batch_size),
                    )
                    removed = cursor.rowcount
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

                deleted += removed
                if removed < batch_size:
                    break

            entry_count = self._count_with_connection(connection)
            database_size = self._database_size_with_connection(connection)
            if database_size > max_bytes:
                # Reclaim pages released by expired rows before deciding that
                # any live cache data must be evicted.
                self._incremental_vacuum_to_size(
                    connection,
                    target_bytes=max_bytes,
                )
                database_size = self._database_size_with_connection(connection)

            count_over_limit = entry_count > max_entries
            size_over_limit = database_size > max_bytes
            target_entries = (
                int(max_entries * target_ratio)
                if count_over_limit
                else entry_count
            )
            target_bytes = (
                int(max_bytes * target_ratio)
                if size_over_limit
                else database_size
            )

            while entry_count > target_entries or database_size > target_bytes:
                removed = 0
                connection.execute("BEGIN IMMEDIATE")
                try:
                    if entry_count > target_entries:
                        cursor = connection.execute(
                            """
                            DELETE FROM domain_cache
                            WHERE domain IN (
                                SELECT domain
                                FROM domain_cache
                                ORDER BY last_accessed_at, domain
                                LIMIT ?
                            )
                            """,
                            (
                                min(
                                    batch_size,
                                    entry_count - target_entries,
                                ),
                            ),
                        )
                    else:
                        # For a size-only overflow, discard reconstructable
                        # cooldown state before useful registration results.
                        cursor = connection.execute(
                            """
                            DELETE FROM rdap_endpoint_backoff
                            WHERE endpoint IN (
                                SELECT endpoint
                                FROM rdap_endpoint_backoff
                                ORDER BY observed_at, endpoint
                                LIMIT ?
                            )
                            """,
                            (batch_size,),
                        )
                        if cursor.rowcount == 0 and entry_count > 0:
                            cursor = connection.execute(
                                """
                                DELETE FROM domain_cache
                                WHERE domain IN (
                                    SELECT domain
                                    FROM domain_cache
                                    ORDER BY last_accessed_at, domain
                                    LIMIT ?
                                )
                                """,
                                (min(batch_size, entry_count),),
                            )
                        if cursor.rowcount == 0:
                            cursor = connection.execute(
                                "DELETE FROM rdap_bootstrap_cache WHERE singleton_id = 1"
                            )

                    removed = cursor.rowcount
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

                deleted += removed
                if removed == 0:
                    # The irreducible schema/maintenance pages may exceed an
                    # artificially tiny configured limit.
                    break
                if size_over_limit:
                    self._incremental_vacuum_to_size(
                        connection,
                        target_bytes=target_bytes,
                    )
                entry_count = self._count_with_connection(connection)
                database_size = self._database_size_with_connection(connection)

            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    UPDATE cache_maintenance
                    SET pruned_through = MAX(pruned_through, ?),
                        last_pruned_at = MAX(COALESCE(last_pruned_at, ?), ?)
                    WHERE singleton_id = 1
                    """,
                    (prune_through, now, now),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

            return deleted
        finally:
            connection.close()

    @staticmethod
    def _record_write_with_connection(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE cache_maintenance
            SET write_sequence = write_sequence + 1
            WHERE singleton_id = 1
            """
        )

    def maintenance_due(
        self,
        now: int,
        *,
        max_interval_seconds: int,
        max_writes: int,
    ) -> bool:
        if max_interval_seconds <= 0:
            raise ValueError("max_interval_seconds must be positive")
        if max_writes <= 0:
            raise ValueError("max_writes must be positive")

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT write_sequence, pruned_through, last_pruned_at
                FROM cache_maintenance
                WHERE singleton_id = 1
                """
            ).fetchone()
            if row is None or row["last_pruned_at"] is None:
                return True
            return (
                int(row["write_sequence"]) - int(row["pruned_through"])
                >= max_writes
                or now - int(row["last_pruned_at"]) >= max_interval_seconds
            )
        finally:
            connection.close()

    def count(self) -> int:
        connection = self._connect()
        try:
            return self._count_with_connection(connection)
        finally:
            connection.close()

    def database_size_bytes(self) -> int:
        connection = self._connect()
        try:
            return self._database_size_with_connection(connection)
        finally:
            connection.close()

    @staticmethod
    def _count_with_connection(connection: sqlite3.Connection) -> int:
        return int(
            connection.execute("SELECT COUNT(*) FROM domain_cache").fetchone()[0]
        )

    @staticmethod
    def _database_size_with_connection(connection: sqlite3.Connection) -> int:
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        return page_count * page_size

    @classmethod
    def _incremental_vacuum_to_size(
        cls,
        connection: sqlite3.Connection,
        *,
        target_bytes: int,
    ) -> None:
        """Return free tail pages until the database reaches ``target_bytes``.

        SQLite may release only one page for a single incremental-vacuum
        statement even when a larger page count is requested. Keep asking
        while the file or freelist shrinks; stop if SQLite can make no further
        progress or the remaining pages contain live schema/bootstrap data.
        """

        while cls._database_size_with_connection(connection) > target_bytes:
            before_page_count = int(
                connection.execute("PRAGMA page_count").fetchone()[0]
            )
            before_freelist_count = int(
                connection.execute("PRAGMA freelist_count").fetchone()[0]
            )
            if before_freelist_count <= 0:
                return

            connection.execute(
                f"PRAGMA incremental_vacuum({before_freelist_count})"
            )
            after_page_count = int(
                connection.execute("PRAGMA page_count").fetchone()[0]
            )
            after_freelist_count = int(
                connection.execute("PRAGMA freelist_count").fetchone()[0]
            )
            if (
                after_page_count >= before_page_count
                and after_freelist_count >= before_freelist_count
            ):
                return

    def get_bootstrap(self) -> BootstrapCacheEntry | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT payload, fetched_at, fresh_until, etag, last_modified
                FROM rdap_bootstrap_cache
                WHERE singleton_id = 1
                """
            ).fetchone()
            if row is None:
                return None

            return BootstrapCacheEntry(
                payload=row["payload"],
                fetched_at=row["fetched_at"],
                fresh_until=row["fresh_until"],
                etag=row["etag"],
                last_modified=row["last_modified"],
            )
        finally:
            connection.close()

    def put_bootstrap(
        self,
        payload: str,
        fetched_at: int,
        fresh_until: int,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO rdap_bootstrap_cache (
                    singleton_id, payload, fetched_at, fresh_until,
                    etag, last_modified
                ) VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    payload = excluded.payload,
                    fetched_at = excluded.fetched_at,
                    fresh_until = excluded.fresh_until,
                    etag = excluded.etag,
                    last_modified = excluded.last_modified
                WHERE excluded.fetched_at >= rdap_bootstrap_cache.fetched_at
                """,
                (payload, fetched_at, fresh_until, etag, last_modified),
            )
            if cursor.rowcount > 0:
                self._record_write_with_connection(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        normalized = endpoint.strip().rstrip("/")
        if not normalized or len(normalized) > 2_048:
            raise ValueError("endpoint is empty or too long")
        return normalized

    def get_endpoint_backoff(self, endpoint: str) -> int | None:
        normalized_endpoint = self._normalize_endpoint(endpoint)
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT retry_after
                FROM rdap_endpoint_backoff
                WHERE endpoint = ?
                """,
                (normalized_endpoint,),
            ).fetchone()
            return None if row is None else int(row["retry_after"])
        finally:
            connection.close()

    def put_endpoint_backoff(
        self,
        endpoint: str,
        retry_after: int,
        observed_at: int,
    ) -> None:
        if retry_after <= observed_at:
            raise ValueError("retry_after must be later than observed_at")

        normalized_endpoint = self._normalize_endpoint(endpoint)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO rdap_endpoint_backoff (
                    endpoint, retry_after, observed_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                    retry_after = MAX(
                        excluded.retry_after,
                        rdap_endpoint_backoff.retry_after
                    ),
                    observed_at = MAX(
                        excluded.observed_at,
                        rdap_endpoint_backoff.observed_at
                    )
                WHERE
                    excluded.retry_after > rdap_endpoint_backoff.retry_after
                    OR excluded.observed_at > rdap_endpoint_backoff.observed_at
                """,
                (normalized_endpoint, retry_after, observed_at),
            )
            if cursor.rowcount > 0:
                self._record_write_with_connection(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
