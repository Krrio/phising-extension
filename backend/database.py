from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Column, JSON
from sqlmodel import Field, Session, SQLModel, create_engine


DATABASE_PATH = Path(__file__).resolve().parent / "history.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


class AnalysisHistory(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
    )
    trust_score: int
    verdict: str = Field(index=True)
    confidence: float
    reasoning: str
    categories: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session