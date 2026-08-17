from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PolicyAssessment(BaseModel):
    """Structured effect of an organization policy on the final verdict."""

    model_config = ConfigDict(extra="forbid")

    violated: bool
    influence: Literal["none", "supporting", "material"]
    summary: str | None = Field(default=None, max_length=500)
    # The Crew decides only the policy effect. The API attaches trusted
    # request metadata after structured output validation, so the model does
    # not need to reproduce a long hash or a potentially unusual file name.
    policyHash: str = Field(default="", max_length=128)
    policyFileName: str = Field(default="", max_length=255)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("policy summary cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_no_violation_assessment(self) -> "PolicyAssessment":
        if not self.violated and (
            self.influence != "none" or self.summary is not None
        ):
            raise ValueError(
                "a non-violation must have influence='none' and summary=null"
            )
        if self.violated and self.summary is None:
            raise ValueError("a policy violation requires a summary")
        if self.violated and self.influence == "none":
            raise ValueError(
                "a policy violation must have supporting or material influence"
            )
        return self


class GuardianVerdict(BaseModel):
    """Wynik analizy phishingowej zwracany przez crew"""

    model_config = ConfigDict(extra="forbid")

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
    policyAssessment: PolicyAssessment | None = None
