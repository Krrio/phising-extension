from datetime import datetime, timezone
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from guardian_classic.tools.domain_age_logic import (
    format_domain_registration,
    get_domain_registration,
)


class DomainAgeInput(BaseModel):
    """Input schema for DomainAgeTool."""

    domains: str = Field(
        ...,
        description="Lista domen do sprawdzenia, oddzielona przecinkami",
    )


class DomainAgeTool(BaseTool):
    name: str = "Sprawdzanie wieku domeny"
    description: str = (
        "Sprawdza przez RDAP (z awaryjnym fallbackiem WHOIS), jak dawno "
        "zarejestrowano domenę. "
        "Domeny zarejestrowane niedawno (poniżej 90 dni) są częstym narzędziem "
        "phishingu, ponieważ atakujący tworzą je na potrzeby jednej kampanii. "
        "Stary wiek domeny NIE oznacza automatycznie, że jest bezpieczna — "
        "to tylko jeden z sygnałów, który należy zważyć z innymi."
    )
    args_schema: Type[BaseModel] = DomainAgeInput

    def _run(self, domains: str) -> str:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

        if not domain_list:
            return "Nie podano żadnych domen."

        results = []
        for domain in domain_list:
            registration = get_domain_registration(domain)
            results.append(
                format_domain_registration(
                    domain,
                    registration,
                    as_of=datetime.now(timezone.utc),
                )
            )

        return "\n".join(results)
