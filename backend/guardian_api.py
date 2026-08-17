import json
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from guardian_classic.crew import GuardianClassic

load_dotenv(Path(__file__).parent / "guardian" / ".env")

router = APIRouter(prefix="/guardian")

Domain = Annotated[str, StringConstraints(max_length=253)]
Phrase = Annotated[str, StringConstraints(max_length=200)]


class LinkMismatch(BaseModel):
    text: str = Field(max_length=200)
    href: str = Field(max_length=2_048)


class GuardianRequest(BaseModel):
    content: str = Field(max_length=8_000)
    domains: list[Domain] = Field(default_factory=list, max_length=20)
    phrases: list[Phrase] = Field(default_factory=list, max_length=50)
    linkMismatches: list[LinkMismatch] = Field(default_factory=list, max_length=50)


@router.post("/analyze")
def guardian_analyze(request: GuardianRequest):
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
        "domains": ", ".join(request.domains) or "brak",
        "untrusted_payload": untrusted_payload,
    }

    try:
        result = GuardianClassic().crew().kickoff(inputs=inputs)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Crew failed: {error}")

    if result.pydantic is None:
        raise HTTPException(status_code=500, detail="Crew nie zwrócił struktury.")

    return result.pydantic
