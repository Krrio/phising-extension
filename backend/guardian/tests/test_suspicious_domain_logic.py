import unittest

from guardian_classic.tools.suspicious_domain_logic import (
    analyze_domain,
    is_suspicious_domain,
    parse_hostname,
)


class SuspiciousDomainLogicTests(unittest.TestCase):
    def test_detects_typo_and_character_substitution(self) -> None:
        for domain in ("paypa1.com", "g00gle.com"):
            with self.subTest(domain=domain):
                analysis = analyze_domain(domain)
                self.assertTrue(analysis.is_suspicious)
                self.assertEqual("leet", analysis.provenance)
                self.assertIn("character-substitution", analysis.reasons)

        self.assertEqual("paypal", analyze_domain("paypa1.com").matched_brand)
        self.assertEqual("google", analyze_domain("g00gle.com").matched_brand)

    def test_keeps_fuzzy_match_provenance(self) -> None:
        analysis = analyze_domain("paypol.com")

        self.assertTrue(analysis.is_suspicious)
        self.assertEqual("paypal", analysis.matched_brand)
        self.assertEqual("fuzzy", analysis.provenance)
        self.assertIn("lookalike-spelling", analysis.reasons)

    def test_detects_numeric_affix_beside_brand(self) -> None:
        for domain in (
            "paypal123.com",
            "123paypal.com",
            "office365123.de",
            "przelewy24123.com",
        ):
            with self.subTest(domain=domain):
                analysis = analyze_domain(domain)
                self.assertTrue(analysis.is_suspicious)
                self.assertIn("numeric-affix", analysis.reasons)

        self.assertEqual(
            "office365",
            analyze_domain("office365123.de").matched_brand,
        )

    def test_detects_unrecognized_separator_inside_brand(self) -> None:
        analysis = analyze_domain("pay-pal.com")

        self.assertTrue(analysis.is_suspicious)
        self.assertIn("brand-label-obfuscation", analysis.reasons)

    def test_allows_official_separator_form_on_regional_suffix(self) -> None:
        for domain in ("t-mobile.de", "x-kom.de", "credit-agricole.de"):
            with self.subTest(domain=domain):
                self.assertFalse(is_suspicious_domain(domain))

    def test_trusts_official_domains_and_their_real_subdomains(self) -> None:
        for domain in ("paypal.com", "www.paypal.com", "mail.google.com"):
            with self.subTest(domain=domain):
                self.assertFalse(is_suspicious_domain(domain))

    def test_does_not_flag_unrelated_or_non_domain_inputs(self) -> None:
        for domain in (
            "example.com",
            "localhost",
            "127.0.0.1",
            "appleid.invalid",
            "",
            "[",
        ):
            with self.subTest(domain=domain):
                self.assertFalse(is_suspicious_domain(domain))

    def test_allows_plain_regional_company_domains(self) -> None:
        for domain in (
            "google.de",
            "google.fr",
            "google.co.uk",
            "amazon.it",
            "huawei.de",
            "lenovo.fr",
            "visa.co.uk",
            "pzu.com",
        ):
            with self.subTest(domain=domain):
                self.assertFalse(is_suspicious_domain(domain))

    def test_allows_subdomains_of_unverified_regional_company_domains(self) -> None:
        for domain in (
            "support.google.de",
            "mail.google.de",
            "apple.google.de",
        ):
            with self.subTest(domain=domain):
                analysis = analyze_domain(domain)
                self.assertFalse(analysis.is_suspicious)
                self.assertEqual(("unverified-regional-brand",), analysis.reasons)
                self.assertEqual("raw", analysis.provenance)

    def test_detects_suspicious_addition_in_same_label(self) -> None:
        for domain in (
            "paypal-login.com",
            "allegro-pomoc.net",
            "paypal-login.co.uk",
        ):
            with self.subTest(domain=domain):
                analysis = analyze_domain(domain)
                self.assertTrue(analysis.is_suspicious)
                self.assertEqual("addition-stripped", analysis.provenance)
                self.assertIn("suspicious-addition", analysis.reasons)

    def test_detects_brand_in_foreign_subdomain(self) -> None:
        for domain, brand in (
            ("paypal.secure-verify.com", "paypal"),
            ("google.evil.co.uk", "google"),
        ):
            with self.subTest(domain=domain):
                analysis = analyze_domain(domain)
                self.assertTrue(analysis.is_suspicious)
                self.assertEqual(brand, analysis.matched_brand)
                self.assertIn("brand-in-foreign-subdomain", analysis.reasons)

    def test_uses_risky_public_suffix_as_supporting_evidence(self) -> None:
        for domain in ("google.xyz", "pzu.top", "amazon.tk"):
            with self.subTest(domain=domain):
                analysis = analyze_domain(domain)
                self.assertTrue(analysis.is_suspicious)
                self.assertIn("risky-public-suffix", analysis.reasons)

    def test_uses_private_hosting_suffix_as_supporting_evidence(self) -> None:
        for domain in ("paypal.github.io", "paypal.s3.amazonaws.com"):
            with self.subTest(domain=domain):
                analysis = analyze_domain(domain)
                self.assertTrue(analysis.is_suspicious)
                self.assertIn("private-or-shared-hosting", analysis.reasons)

    def test_keeps_lookalike_detection_on_compound_public_suffix(self) -> None:
        analysis = analyze_domain("g00gle.co.uk")

        self.assertTrue(analysis.is_suspicious)
        self.assertEqual("leet", analysis.provenance)
        self.assertIn("character-substitution", analysis.reasons)

    def test_does_not_extend_amazonaws_allowlist_to_tenants(self) -> None:
        self.assertFalse(is_suspicious_domain("amazonaws.com"))

        analysis = analyze_domain("paypal.amazonaws.com")
        self.assertTrue(analysis.is_suspicious)
        self.assertIn("brand-in-foreign-subdomain", analysis.reasons)
        self.assertIn("private-or-shared-hosting", analysis.reasons)

    def test_does_not_grant_regional_policy_to_product_aliases(self) -> None:
        analysis = analyze_domain("appleid.de")

        self.assertTrue(analysis.is_suspicious)
        self.assertIn("non-regional-brand-domain", analysis.reasons)

    def test_extracts_hostname_from_url(self) -> None:
        analysis = analyze_domain(
            "https://paypal-login.com/account?next=home#verification"
        )

        self.assertEqual("paypal-login.com", analysis.hostname)
        self.assertTrue(analysis.is_suspicious)

    def test_canonicalizes_idn_hostname_to_ascii(self) -> None:
        analysis = analyze_domain("https://żółć.pl")

        self.assertEqual("xn--kda4b0koi.pl", analysis.hostname)
        self.assertFalse(analysis.is_suspicious)

    def test_public_suffix_parser_handles_compound_and_private_suffixes(self) -> None:
        compound = parse_hostname("support.google.co.uk")
        self.assertIsNotNone(compound)
        assert compound is not None
        self.assertEqual("google.co.uk", compound.domain)
        self.assertEqual("google", compound.domain_without_suffix)
        self.assertEqual("co.uk", compound.public_suffix)
        self.assertEqual("support", compound.subdomain)
        self.assertTrue(compound.is_icann)
        self.assertFalse(compound.is_private)

        private = parse_hostname("paypal.github.io")
        self.assertIsNotNone(private)
        assert private is not None
        self.assertEqual("paypal.github.io", private.domain)
        self.assertEqual("paypal", private.domain_without_suffix)
        self.assertEqual("github.io", private.public_suffix)
        self.assertEqual("", private.subdomain)
        self.assertFalse(private.is_icann)
        self.assertTrue(private.is_private)


if __name__ == "__main__":
    unittest.main()
