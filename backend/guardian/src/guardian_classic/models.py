from typing import Literal

from pydantic import BaseModel, Field

class GuardianVerdict(BaseModel):
    """Wynik analizy phishingowej zwracany przez crew"""

    trustScore: int = Field(ge=0, le=100)
    verdict: Literal["safe", "suspicious", "phishing"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    categories: list[
        Literal[
            "credential_request",
            "urgency",
            "impersonation",
            "suspicious_link",
            "suspicious_domain",
            "financial",
        ]
    ]