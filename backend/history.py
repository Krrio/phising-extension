from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import func

from database import AnalysisHistory, get_session

router = APIRouter(prefix="/history", tags=["history"])

class TrustScorePoint(BaseModel):
    timestamp: datetime
    trustScore: int

@router.get("/trust-score", response_model=list[TrustScorePoint])
def get_trust_score_history(
    session: Session = Depends(get_session),
) -> list[TrustScorePoint]:
    statement = select(AnalysisHistory).order_by(AnalysisHistory.timestamp)
    entries = session.exec(statement).all()

    return [
        TrustScorePoint(
            timestamp=(
                entry.timestamp.replace(tzinfo=timezone.utc)
                if entry.timestamp.tzinfo is None
                else entry.timestamp
            ),
            trustScore=entry.trust_score,
        )
        for entry in entries
    ]

class VerdictDistribution(BaseModel):
    safe: int
    suspicious: int
    phishing: int


@router.get("/verdicts", response_model=VerdictDistribution)
def get_verdict_distribution(
    session: Session = Depends(get_session),
) -> VerdictDistribution:
    statement = (
        select(
            AnalysisHistory.verdict,
            func.count(AnalysisHistory.id),
        )
        .group_by(AnalysisHistory.verdict)
    )

    rows = session.exec(statement).all()

    counts = {
        "safe": 0,
        "suspicious": 0,
        "phishing": 0
    }

    for verdict, count in rows:
        if verdict in counts:
            counts[verdict] = count
    
    return VerdictDistribution(**counts)

class CategoryDistribution(BaseModel):
    credential_request: int
    urgency: int
    impersonation: int
    suspicious_link: int
    suspicious_domain: int
    financial: int

CATEGORY_NAMES = (
    "credential_request",
    "urgency",
    "impersonation",
    "suspicious_link",
    "suspicious_domain",
    "financial",
)

@router.get("/categories", response_model=CategoryDistribution)
def get_category_distribution(
    session: Session = Depends(get_session),
) -> CategoryDistribution:
    statement = select(AnalysisHistory.categories)
    category_lists = session.exec(statement).all()

    counts = {
        category: 0 for category in CATEGORY_NAMES
    }

    for categories in category_lists:
        for category in set(categories):
            if category in counts:
                counts[category] += 1
    return CategoryDistribution(**counts)
