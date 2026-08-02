from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from guardian_classic.tools.suspicious_domain_logic import is_suspicious_domain


class SuspiciousDomainInput(BaseModel):
    """Input schema for SuspiciousDomainTool."""

    domains: str = Field(
        ...,
        description="Lista domen do sprawdzenia, oddzielona przecinkami, np. 'paypa1.com, google.com'",
    )


class SuspiciousDomainTool(BaseTool):
    name: str = "Detektor podejrzanych domen"
    description: str = (
        "Sprawdza domeny pod kątem typosquattingu i podszywania się pod znane marki. "
        "Wykrywa podmiany znaków (paypa1.com zamiast paypal.com), nazwy marek na "
        "nieoficjalnych domenach (paypal-login.com) oraz literówki. "
        "Używaj ZAWSZE, gdy masz do oceny jakąkolwiek domenę — wynik jest oparty na "
        "bazie ponad 200 znanych marek i liście oficjalnych domen, nie na domysłach."
    )
    args_schema: Type[BaseModel] = SuspiciousDomainInput

    def _run(self, domains: str) -> str:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

        if not domain_list:
            return "Nie podano żadnych domen do sprawdzenia."

        results = []
        for domain in domain_list:
            if is_suspicious_domain(domain):
                results.append(
                    f"{domain}: PODEJRZANA — przypomina znaną markę lub zawiera jej "
                    f"nazwę na nieoficjalnej domenie"
                )
            else:
                results.append(f"{domain}: CZYSTA — brak dopasowania do znanych marek")

        return "\n".join(results)