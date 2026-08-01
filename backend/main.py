from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from history import router as history_router
from guardian_api import router as guardian_router


from database import create_db_and_tables

@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(history_router)
app.include_router(guardian_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://ackfaohibedfakhaaffgkjfjcjmecghp",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)
