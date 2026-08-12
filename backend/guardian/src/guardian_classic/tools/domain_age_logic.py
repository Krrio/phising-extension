"""Compatibility wrapper for the domain-age CrewAI tool."""

from datetime import datetime

from guardian_classic.domain_registration import (
    DomainRegistrationResult,
    get_default_service,
)


def get_domain_registration(domain: str) -> DomainRegistrationResult:
    """Zwraca pełny, typowany wynik zamiast gubić przyczynę braku wieku."""
    return get_default_service().get_registration(domain)


def get_domain_age_days(domain: str) -> int | None:
    """Zwraca wiek domeny w dniach albo None, jeśli nie udało się ustalić."""
    return get_default_service().get_domain_age_days(domain)


def format_domain_registration(
    requested_domain: str,
    registration: DomainRegistrationResult,
    *,
    as_of: datetime,
) -> str:
    """Render a result without collapsing meaningful failure statuses."""

    age = registration.age_days(as_of)
    if registration.status == "not_found":
        return (
            f"{requested_domain}: domena nie została znaleziona w rejestrze "
            "(może być niezarejestrowana)"
        )
    if registration.status == "not_applicable":
        return f"{requested_domain}: to nie jest publiczna domena rejestrowalna"
    if registration.status == "unsupported":
        return f"{requested_domain}: rejestr nie udostępnia daty rejestracji"
    if registration.status == "unavailable":
        return (
            f"{requested_domain}: rejestr jest chwilowo niedostępny; "
            "wieku nie ustalono"
        )
    if age is None:
        return f"{requested_domain}: nie udało się ustalić daty rejestracji"
    if age < 90:
        return (
            f"{requested_domain}: zarejestrowana {age} dni temu — BARDZO ŚWIEŻA"
        )
    if age < 365:
        return f"{requested_domain}: zarejestrowana {age} dni temu (poniżej roku)"
    return (
        f"{requested_domain}: zarejestrowana {age} dni temu (~{age // 365} lat)"
    )
