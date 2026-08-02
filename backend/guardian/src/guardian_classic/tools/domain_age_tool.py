from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from guardian_classic.tools.domain_age_logic import get_domain_age_days

class DomainAgeInput(BaseModel):
    """Input schema for DomainAgeTool."""

    domains: str = Field(
        ...,
        description="Lista domen do sprawdzenia, oddzielona przecinkami"
    )

class DomainAgeTool(BaseTool):
    name: str = "Sprawdzanie wieku domeny"
    description: str = (
        "Sprawdza w rejestrze WHOIS, jak dawno zarejestrowano domenę. "
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
            age = get_domain_age_days(domain)
            if age is None:
                results.append(f"{domain}: nie udało się ustalić daty rejestracji")
            elif age < 90:
                results.append(f"{domain}: zarejestrowana {age} dni temu — BARDZO ŚWIEŻA")
            elif age < 365:
                results.append(f"{domain}: zarejestrowana {age} dni temu (poniżej roku)")
            else:
                results.append(f"{domain}: zarejestrowana {age} dni temu (~{age // 365} lat)")
            
        return "\n".join(results)
