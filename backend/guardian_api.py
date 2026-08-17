import hashlib
import ipaddress
import json
import re
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from guardian_classic.crew import GuardianClassic
from guardian_classic.models import GuardianVerdict

load_dotenv(Path(__file__).parent / "guardian" / ".env")

router = APIRouter(prefix="/guardian")

Domain = Annotated[str, StringConstraints(max_length=253)]
Phrase = Annotated[str, StringConstraints(max_length=200)]
MAX_ORGANIZATION_POLICY_BYTES = 50 * 1024
MAX_POLICY_FILE_NAME_LENGTH = 255
POLICY_HASH_LENGTH = 64
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class LinkMismatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=200)
    href: str = Field(max_length=2_048)


class OrganizationPolicy(BaseModel):
    """Stateless organization policy supplied with one analysis request."""

    model_config = ConfigDict(extra="forbid")

    content: str
    fileName: str = Field(min_length=1, max_length=MAX_POLICY_FILE_NAME_LENGTH)
    contentHash: str = Field(
        min_length=POLICY_HASH_LENGTH,
        max_length=POLICY_HASH_LENGTH,
        pattern=r"^[a-f0-9]{64}$",
    )
    sizeBytes: int = Field(strict=True, ge=1, le=MAX_ORGANIZATION_POLICY_BYTES)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("organization policy cannot contain NUL characters")
        if not value.replace("\ufeff", "").strip():
            raise ValueError("organization policy cannot be blank")

        try:
            size_bytes = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValueError("organization policy must be valid UTF-8") from error

        if size_bytes > MAX_ORGANIZATION_POLICY_BYTES:
            raise ValueError(
                "organization policy cannot exceed 50 KiB encoded as UTF-8"
            )
        return value

    @field_validator("fileName")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        if "\0" in value or not value.strip():
            raise ValueError("organization policy file name cannot be blank")
        if not value.lower().endswith((".md", ".txt")):
            raise ValueError("organization policy must be a .md or .txt file")
        return value

    @model_validator(mode="after")
    def validate_content_identity(self) -> "OrganizationPolicy":
        content_bytes = self.content.encode("utf-8")
        if self.contentHash != hashlib.sha256(content_bytes).hexdigest():
            raise ValueError("organization policy hash does not match its content")
        # Frontend removes an optional leading UTF-8 BOM from content while
        # preserving it in original file-size metadata.
        if self.sizeBytes not in (len(content_bytes), len(content_bytes) + 3):
            raise ValueError("organization policy byte size does not match its content")
        return self


class GuardianRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=8_000)
    domains: list[Domain] = Field(default_factory=list, max_length=20)
    phrases: list[Phrase] = Field(default_factory=list, max_length=50)
    linkMismatches: list[LinkMismatch] = Field(default_factory=list, max_length=50)
    organizationPolicy: OrganizationPolicy | None = None

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            hostname = value.strip().lower().removesuffix(".")
            try:
                ip = ipaddress.ip_address(hostname.strip("[]"))
            except ValueError:
                if not HOSTNAME_PATTERN.fullmatch(hostname):
                    raise ValueError(
                        "domains must contain canonical DNS hostnames or IP addresses"
                    )
                normalized.append(hostname)
            else:
                normalized.append(ip.compressed)
        return normalized


def _policy_payload(policy: OrganizationPolicy | None) -> str:
    if policy is None:
        return "null"
    return json.dumps(policy.model_dump(), ensure_ascii=False)


def _normalize_policy_assessment(
    verdict: GuardianVerdict,
    policy: OrganizationPolicy | None,
) -> GuardianVerdict:
    if policy is None:
        return verdict.model_copy(update={"policyAssessment": None})

    assessment = verdict.policyAssessment
    if assessment is None:
        raise HTTPException(
            status_code=500,
            detail="Crew nie zwrócił oceny polityki organizacji.",
        )

    normalized_assessment = assessment.model_copy(
        update={
            "policyHash": policy.contentHash,
            "policyFileName": policy.fileName,
        }
    )
    return verdict.model_copy(update={"policyAssessment": normalized_assessment})


@router.post("/analyze", response_model=GuardianVerdict)
def guardian_analyze(request: GuardianRequest) -> GuardianVerdict:
    untrusted_payload = json.dumps(
        {
            "content": request.content,
            "phrases": request.phrases,
            "link_mismatches": [
                mismatch.model_dump() for mismatch in request.linkMismatches
            ],
        },
        ensure_ascii=False,
    )
    inputs = {
        "domains_payload": json.dumps(
            {"domains": request.domains},
            ensure_ascii=False,
        ),
        "untrusted_payload": untrusted_payload,
        "policy_payload": _policy_payload(request.organizationPolicy),
    }

    try:
        result = GuardianClassic().crew().kickoff(inputs=inputs)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Crew failed: {error}")

    if result.pydantic is None:
        raise HTTPException(status_code=500, detail="Crew nie zwrócił struktury.")

    return _normalize_policy_assessment(
        result.pydantic,
        request.organizationPolicy,
    )
