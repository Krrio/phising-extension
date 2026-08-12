import unittest
from datetime import datetime, timedelta, timezone

from guardian_classic.domain_registration import DomainRegistrationResult
from guardian_classic.tools.domain_age_logic import format_domain_registration


UTC = timezone.utc


class DomainAgeFormattingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    def render(self, result: DomainRegistrationResult) -> str:
        return format_domain_registration(
            "example.com",
            result,
            as_of=self.now,
        )

    def test_not_found_is_not_collapsed_into_generic_failure(self) -> None:
        rendered = self.render(
            DomainRegistrationResult("example.com", "not_found", source="rdap")
        )

        self.assertIn("nie została znaleziona", rendered)
        self.assertNotIn("nie udało się", rendered)

    def test_transient_and_unsupported_results_are_distinct(self) -> None:
        unavailable = self.render(
            DomainRegistrationResult("example.com", "unavailable")
        )
        unsupported = self.render(
            DomainRegistrationResult("example.com", "unsupported")
        )

        self.assertIn("chwilowo niedostępny", unavailable)
        self.assertIn("nie udostępnia", unsupported)

    def test_success_is_formatted_from_registration_timestamp(self) -> None:
        rendered = self.render(
            DomainRegistrationResult(
                "example.com",
                "success",
                registered_at=self.now - timedelta(days=10),
                source="rdap",
            )
        )

        self.assertIn("10 dni temu", rendered)
        self.assertIn("BARDZO ŚWIEŻA", rendered)


if __name__ == "__main__":
    unittest.main()
