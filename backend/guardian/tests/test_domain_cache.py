import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from guardian_classic.domain_cache import (
    BootstrapCacheEntry,
    DomainRegistrationCache,
)


class DomainRegistrationCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "domains.sqlite3"
        self.cache = DomainRegistrationCache(self.database_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def put_success(
        self,
        domain: str,
        *,
        fetched_at: int = 100,
        fresh_until: int = 200,
        stale_until: int = 300,
    ) -> None:
        self.cache.put_success(
            domain,
            1_600_000_000,
            "rdap",
            fetched_at,
            fresh_until,
            stale_until,
            2,
        )

    def test_success_survives_new_cache_instance(self) -> None:
        self.assertIsNone(self.cache.get("example.com"))

        self.put_success("Example.COM.")
        restarted_cache = DomainRegistrationCache(self.database_path)
        entry = restarted_cache.get("example.com")

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual("example.com", entry.domain)
        self.assertEqual("success", entry.status)
        self.assertEqual(1_600_000_000, entry.registered_at)
        self.assertEqual("rdap", entry.source)
        self.assertEqual(100, entry.fetched_at)
        self.assertEqual(200, entry.fresh_until)
        self.assertEqual(300, entry.stale_until)
        self.assertIsNone(entry.retry_after)
        self.assertEqual(100, entry.last_accessed_at)
        self.assertIsNone(entry.error_code)
        self.assertEqual(2, entry.parser_version)

    def test_upserts_between_failure_and_success(self) -> None:
        self.cache.put_failure(
            "example.com",
            "not_found",
            "rdap",
            10,
            20,
            15,
            "http-404",
            1,
        )
        failure = self.cache.get("example.com")
        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual("not_found", failure.status)
        self.assertIsNone(failure.registered_at)
        self.assertIsNone(failure.stale_until)
        self.assertEqual(15, failure.retry_after)
        self.assertEqual("http-404", failure.error_code)

        self.put_success("example.com")
        success = self.cache.get("example.com")
        self.assertIsNotNone(success)
        assert success is not None
        self.assertEqual("success", success.status)
        self.assertEqual(300, success.stale_until)
        self.assertIsNone(success.retry_after)
        self.assertIsNone(success.error_code)

        self.cache.put_failure(
            "example.com",
            "parse_error",
            "whois",
            400,
            500,
            error_code="bad-date",
            parser_version=3,
        )
        replaced = self.cache.get("example.com")
        self.assertIsNotNone(replaced)
        assert replaced is not None
        self.assertEqual("parse_error", replaced.status)
        self.assertEqual("whois", replaced.source)
        self.assertIsNone(replaced.stale_until)
        self.assertEqual(3, replaced.parser_version)

    def test_postpone_retry_preserves_stale_success(self) -> None:
        self.put_success("example.com")
        before = self.cache.get("example.com")

        changed = self.cache.postpone_retry(
            "example.com",
            250,
            "http-429",
            last_accessed_at=150,
        )
        after = self.cache.get("example.com")

        self.assertTrue(changed)
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        assert before is not None and after is not None
        self.assertEqual("success", after.status)
        self.assertEqual(before.registered_at, after.registered_at)
        self.assertEqual(before.source, after.source)
        self.assertEqual(before.fetched_at, after.fetched_at)
        self.assertEqual(before.fresh_until, after.fresh_until)
        self.assertEqual(before.stale_until, after.stale_until)
        self.assertEqual(before.parser_version, after.parser_version)
        self.assertEqual(250, after.retry_after)
        self.assertEqual("http-429", after.error_code)
        self.assertEqual(150, after.last_accessed_at)

        self.assertTrue(
            self.cache.postpone_retry(
                "example.com",
                240,
                "shorter-delay",
                last_accessed_at=140,
            )
        )
        monotonic = self.cache.get("example.com")
        self.assertIsNotNone(monotonic)
        assert monotonic is not None
        self.assertEqual(250, monotonic.retry_after)
        self.assertEqual(150, monotonic.last_accessed_at)

        self.cache.put_failure(
            "negative.test",
            "transient_error",
            "rdap",
            100,
            200,
        )
        self.assertFalse(self.cache.postpone_retry("negative.test", 250))
        self.assertEqual(
            "transient_error",
            self.cache.get("negative.test").status,  # type: ignore[union-attr]
        )

    def test_non_authoritative_failure_does_not_overwrite_usable_success(self) -> None:
        self.put_success(
            "example.com",
            fetched_at=100,
            fresh_until=150,
            stale_until=300,
        )

        self.cache.put_failure(
            "example.com",
            "transient_error",
            "rdap",
            200,
            220,
            error_code="timeout",
        )

        preserved = self.cache.get("example.com")
        self.assertIsNotNone(preserved)
        assert preserved is not None
        self.assertEqual("success", preserved.status)
        self.assertEqual(1_600_000_000, preserved.registered_at)

        self.cache.put_failure(
            "example.com",
            "not_found",
            "rdap",
            210,
            240,
        )
        authoritative = self.cache.get("example.com")
        self.assertIsNotNone(authoritative)
        assert authoritative is not None
        self.assertEqual("not_found", authoritative.status)

    def test_older_cross_process_results_cannot_replace_newer_rows(self) -> None:
        self.put_success(
            "example.com",
            fetched_at=200,
            fresh_until=300,
            stale_until=400,
        )

        self.cache.put_failure(
            "example.com",
            "not_found",
            "rdap",
            100,
            150,
        )
        after_old_failure = self.cache.get("example.com")
        self.assertIsNotNone(after_old_failure)
        assert after_old_failure is not None
        self.assertEqual("success", after_old_failure.status)
        self.assertEqual(200, after_old_failure.fetched_at)

        self.cache.put_failure(
            "example.com",
            "not_found",
            "rdap",
            300,
            350,
        )
        self.put_success(
            "example.com",
            fetched_at=250,
            fresh_until=350,
            stale_until=450,
        )
        after_old_success = self.cache.get("example.com")
        self.assertIsNotNone(after_old_success)
        assert after_old_success is not None
        self.assertEqual("not_found", after_old_success.status)
        self.assertEqual(300, after_old_success.fetched_at)

    def test_old_refresh_cannot_postpone_a_newer_success(self) -> None:
        self.put_success(
            "example.com",
            fetched_at=200,
            fresh_until=300,
            stale_until=400,
        )

        changed = self.cache.postpone_retry(
            "example.com",
            500,
            "old-timeout",
            last_accessed_at=100,
        )

        self.assertFalse(changed)
        entry = self.cache.get("example.com")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertIsNone(entry.retry_after)
        self.assertIsNone(entry.error_code)

    def test_authoritative_negative_wins_equal_timestamp_failure_race(self) -> None:
        self.cache.put_failure(
            "example.com",
            "not_found",
            "rdap",
            100,
            200,
        )
        self.cache.put_failure(
            "example.com",
            "transient_error",
            "rdap",
            100,
            150,
            error_code="timeout",
        )

        entry = self.cache.get("example.com")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual("not_found", entry.status)
        self.assertEqual(200, entry.fresh_until)

    def test_transient_failure_does_not_replace_fresh_not_found(self) -> None:
        self.cache.put_failure(
            "example.com",
            "not_found",
            "rdap",
            100,
            300,
        )
        self.cache.put_failure(
            "example.com",
            "transient_error",
            "rdap",
            200,
            250,
            error_code="timeout",
        )

        preserved = self.cache.get("example.com")
        self.assertIsNotNone(preserved)
        assert preserved is not None
        self.assertEqual("not_found", preserved.status)
        self.assertEqual(300, preserved.fresh_until)

        self.cache.put_failure(
            "example.com",
            "transient_error",
            "rdap",
            300,
            400,
            error_code="timeout",
        )
        expired = self.cache.get("example.com")
        self.assertIsNotNone(expired)
        assert expired is not None
        self.assertEqual("transient_error", expired.status)

    def test_touch_is_coarse(self) -> None:
        self.put_success("example.com", fetched_at=100)

        self.assertFalse(self.cache.touch("example.com", 200))
        self.assertEqual(
            100,
            self.cache.get("example.com").last_accessed_at,  # type: ignore[union-attr]
        )

        self.assertTrue(self.cache.touch("example.com", 3_700))
        self.assertEqual(
            3_700,
            self.cache.get("example.com").last_accessed_at,  # type: ignore[union-attr]
        )
        self.assertFalse(self.cache.touch("missing.test", 4_000))

    def test_prune_hard_expiration_in_batches(self) -> None:
        self.put_success("expired-success.test", stale_until=1_000)
        self.put_success("stale-success.test", fresh_until=100, stale_until=1_001)
        self.cache.put_failure(
            "expired-negative.test",
            "not_found",
            "rdap",
            100,
            1_000,
        )
        self.cache.put_failure(
            "live-negative.test",
            "unsupported",
            "rdap",
            100,
            1_001,
        )

        deleted = self.cache.prune(1_000, batch_size=1)

        self.assertEqual(2, deleted)
        self.assertIsNone(self.cache.get("expired-success.test"))
        self.assertIsNone(self.cache.get("expired-negative.test"))
        self.assertIsNotNone(self.cache.get("stale-success.test"))
        self.assertIsNotNone(self.cache.get("live-negative.test"))

    def test_prune_evicts_lru_to_limit(self) -> None:
        for index, domain in enumerate(("a.test", "b.test", "c.test", "d.test")):
            self.put_success(
                domain,
                fetched_at=100 + index,
                fresh_until=2_000,
                stale_until=3_000,
            )

        deleted = self.cache.prune(1_000, max_entries=2, batch_size=1)

        self.assertEqual(3, deleted)
        self.assertEqual(1, self.cache.count())
        self.assertIsNone(self.cache.get("a.test"))
        self.assertIsNone(self.cache.get("b.test"))
        self.assertIsNone(self.cache.get("c.test"))
        self.assertIsNotNone(self.cache.get("d.test"))

    def test_prune_enforces_disk_watermark(self) -> None:
        base_size = self.cache.database_size_bytes()
        for index in range(60):
            self.cache.put_failure(
                f"large-{index}.test",
                "parse_error",
                "rdap",
                100 + index,
                10_000,
                error_code="x" * 4_096,
            )

        grown_size = self.cache.database_size_bytes()
        self.assertGreater(grown_size, base_size)
        max_bytes = base_size + ((grown_size - base_size) // 2)

        deleted = self.cache.prune(
            1_000,
            max_entries=100,
            max_bytes=max_bytes,
            target_ratio=1.0,
            batch_size=5,
        )

        self.assertGreater(deleted, 0)
        self.assertLess(self.cache.count(), 60)
        self.assertLessEqual(self.cache.database_size_bytes(), max_bytes)

    def test_prune_reclaims_expired_pages_before_evicting_live_rows(self) -> None:
        self.cache.put_failure(
            "live.test",
            "unsupported",
            "rdap",
            500,
            10_000,
        )
        base_size = self.cache.database_size_bytes()
        for index in range(60):
            self.cache.put_failure(
                f"expired-large-{index}.test",
                "parse_error",
                "rdap",
                100 + index,
                1_000,
                error_code="x" * 4_096,
            )

        grown_size = self.cache.database_size_bytes()
        max_bytes = base_size + ((grown_size - base_size) // 2)
        deleted = self.cache.prune(
            1_000,
            max_entries=100,
            max_bytes=max_bytes,
            target_ratio=1.0,
            batch_size=5,
        )

        self.assertEqual(60, deleted)
        self.assertEqual(1, self.cache.count())
        self.assertIsNotNone(self.cache.get("live.test"))
        self.assertLessEqual(self.cache.database_size_bytes(), max_bytes)

    def test_prune_size_limit_includes_live_endpoint_backoffs(self) -> None:
        base_size = self.cache.database_size_bytes()
        for index in range(100):
            endpoint = f"https://rdap-{index}.example/{'x' * 1_500}"
            self.cache.put_endpoint_backoff(endpoint, 10_000, 100 + index)

        grown_size = self.cache.database_size_bytes()
        self.assertGreater(grown_size, base_size)
        max_bytes = base_size + ((grown_size - base_size) // 2)

        deleted = self.cache.prune(
            1_000,
            max_entries=100,
            max_bytes=max_bytes,
            target_ratio=1.0,
            batch_size=5,
        )

        self.assertGreater(deleted, 0)
        self.assertEqual(0, self.cache.count())
        self.assertLessEqual(self.cache.database_size_bytes(), max_bytes)

    def test_bootstrap_is_singleton_persistent_and_upserted(self) -> None:
        self.assertIsNone(self.cache.get_bootstrap())

        self.cache.put_bootstrap(
            '{"services": []}',
            100,
            200,
            etag='"first"',
            last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        )
        restarted_cache = DomainRegistrationCache(self.database_path)
        self.assertEqual(
            BootstrapCacheEntry(
                payload='{"services": []}',
                fetched_at=100,
                fresh_until=200,
                etag='"first"',
                last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
            ),
            restarted_cache.get_bootstrap(),
        )

        restarted_cache.put_bootstrap('{"services": [1]}', 300, 400)
        self.assertEqual(
            BootstrapCacheEntry(
                payload='{"services": [1]}',
                fetched_at=300,
                fresh_until=400,
                etag=None,
                last_modified=None,
            ),
            self.cache.get_bootstrap(),
        )

        restarted_cache.put_bootstrap('{"services": ["old"]}', 200, 500)
        self.assertEqual(
            '{"services": [1]}',
            self.cache.get_bootstrap().payload,  # type: ignore[union-attr]
        )

        with closing(sqlite3.connect(self.database_path)) as connection:
            bootstrap_count = connection.execute(
                "SELECT COUNT(*) FROM rdap_bootstrap_cache"
            ).fetchone()[0]
        self.assertEqual(1, bootstrap_count)

    def test_schema_pragmas_constraints_count_and_size(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                3,
                connection.execute("PRAGMA user_version").fetchone()[0],
            )
            self.assertEqual(
                2,
                connection.execute("PRAGMA auto_vacuum").fetchone()[0],
            )
            self.assertNotEqual(
                "wal",
                connection.execute("PRAGMA journal_mode").fetchone()[0].lower(),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO domain_cache (
                        domain, status, fetched_at, fresh_until,
                        last_accessed_at, parser_version
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("invalid.test", "invalid", 1, 2, 1, 1),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO domain_cache (
                        domain, status, fetched_at, fresh_until, stale_until,
                        last_accessed_at, parser_version
                    ) VALUES (?, 'success', ?, ?, ?, ?, ?)
                    """,
                    ("missing-date.test", 1, 2, 3, 1, 1),
                )

        self.assertEqual(0, self.cache.count())
        self.put_success("example.com")
        self.assertEqual(1, self.cache.count())
        self.assertGreater(self.cache.database_size_bytes(), 0)

    def test_existing_wal_database_is_switched_back_to_delete_journal(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            self.assertEqual("wal", mode.lower())

        DomainRegistrationCache(self.database_path)

        with closing(sqlite3.connect(self.database_path)) as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual("delete", mode.lower())

    def test_endpoint_backoff_is_shared_and_monotonic(self) -> None:
        endpoint = "https://rdap.example.test/registry/"
        self.assertIsNone(self.cache.get_endpoint_backoff(endpoint))

        self.cache.put_endpoint_backoff(endpoint, 300, 100)
        restarted_cache = DomainRegistrationCache(self.database_path)
        self.assertEqual(300, restarted_cache.get_endpoint_backoff(endpoint))

        restarted_cache.put_endpoint_backoff(endpoint, 250, 50)
        self.assertEqual(300, self.cache.get_endpoint_backoff(endpoint))

        restarted_cache.put_endpoint_backoff(endpoint, 350, 100)
        self.assertEqual(350, self.cache.get_endpoint_backoff(endpoint))

        restarted_cache.put_endpoint_backoff(endpoint, 320, 200)
        self.assertEqual(350, self.cache.get_endpoint_backoff(endpoint))

        self.cache.prune(350)
        self.assertIsNone(self.cache.get_endpoint_backoff(endpoint))

    def test_schema_v1_is_migrated_without_losing_domain_rows(self) -> None:
        self.put_success("example.com")
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("DROP TABLE rdap_endpoint_backoff")
            connection.execute("DROP TABLE cache_maintenance")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()

        migrated = DomainRegistrationCache(self.database_path)

        self.assertIsNotNone(migrated.get("example.com"))
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                3,
                connection.execute("PRAGMA user_version").fetchone()[0],
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(rdap_endpoint_backoff)"
                )
            }
            maintenance_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(cache_maintenance)"
                )
            }
        self.assertEqual({"endpoint", "retry_after", "observed_at"}, columns)
        self.assertEqual(
            {
                "singleton_id",
                "write_sequence",
                "pruned_through",
                "last_pruned_at",
            },
            maintenance_columns,
        )

    def test_maintenance_due_uses_persistent_global_write_sequence(self) -> None:
        self.assertTrue(
            self.cache.maintenance_due(
                1_000,
                max_interval_seconds=1_000,
                max_writes=2,
            )
        )
        self.cache.prune(1_000)
        self.assertFalse(
            self.cache.maintenance_due(
                1_001,
                max_interval_seconds=1_000,
                max_writes=2,
            )
        )

        self.cache.put_failure("one.test", "parse_error", "rdap", 1_001, 5_000)
        self.assertFalse(
            self.cache.maintenance_due(
                1_001,
                max_interval_seconds=1_000,
                max_writes=2,
            )
        )
        restarted = DomainRegistrationCache(self.database_path)
        restarted.put_failure("two.test", "parse_error", "rdap", 1_002, 5_000)
        self.assertTrue(
            self.cache.maintenance_due(
                1_002,
                max_interval_seconds=1_000,
                max_writes=2,
            )
        )

    def test_rejects_invalid_failure_status_and_future_schema(self) -> None:
        with self.assertRaises(ValueError):
            self.cache.put_failure(  # type: ignore[arg-type]
                "example.com",
                "success",
                "rdap",
                1,
                2,
            )

        future_path = Path(self.temporary_directory.name) / "future.sqlite3"
        with closing(sqlite3.connect(future_path)) as connection:
            connection.execute("PRAGMA user_version = 99")
            connection.commit()

        with self.assertRaises(RuntimeError):
            DomainRegistrationCache(future_path)


if __name__ == "__main__":
    unittest.main()
