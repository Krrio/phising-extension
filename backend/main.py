from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Literal
from openai import OpenAI
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import os

load_dotenv()

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

class LinkMissmatch(BaseModel):
    text: str
    href: str

class Signals(BaseModel):
    suspiciousPhrases: list[str]
    linkMismatches: list[LinkMissmatch]
    suspiciousDomains: list[str]

class AnalyzeRequest(BaseModel):
    content: str
    signals: Signals

class AnalyzeResponse(BaseModel):
    trustScore: int = Field(ge=0, le=100)
    verdict: Literal["safe", "suspicious", "phishing"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    categories: list[str]

@app.post("/analyze")
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:

    prompt = f"""
        Jesteś systemem wykrywania phishingu. Oceń poniższą treść.

        TREŚĆ:
        {request.content}

        SYGNAŁY WYKRYTE PRZEZ REGUŁY:
        - podejrzane frazy: {request.signals.suspiciousPhrases}
        - rozjazdy linków: {request.signals.linkMismatches}
        - podejrzane domeny: {request.signals.suspiciousDomains}

        Oceń poziom zaufania (trustScore 0-100, gdzie 100 = w pełni bezpieczne),
        confidence jako liczba od 0.0 do 1.0 (np. 0.95, NIE 95)
        wydaj werdykt, podaj pewność, krótkie uzasadnienie i kategorie zagrożeń.
        WSZYSTKO ZWRACAJ W JĘZKU POLSKIM.
    """

    odpowiedz = client.chat.completions.parse(
        model = "gpt-4o-mini",
        messages = [
            {"role": "user", "content": prompt}
        ],
        response_format = AnalyzeResponse,
        temperature=0
    )
    return odpowiedz.choices[0].message.parsed