from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from guardian_classic.crew import GuardianClassic

load_dotenv(Path(__file__).parent / "guardian" / ".env")

router = APIRouter(prefix="/guardian")
    

class GuardianRequest(BaseModel):
    content: str
    domains: list[str] = []
    phrases: list[str] = []


@router.post("/analyze")
def guardian_analyze(request: GuardianRequest):
    inputs = {
        "content": request.content,
        "domains": ", ".join(request.domains) or "brak",
        "phrases": ", ".join(request.phrases) or "brak",
    }

    try:
        result = GuardianClassic().crew().kickoff(inputs=inputs)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Crew failed: {error}")

    if result.pydantic is None:
        raise HTTPException(status_code=500, detail="Crew nie zwrócił struktury.")

    return result.pydantic