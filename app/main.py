from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import initialize_database
from app.routers.analyze import router as analyze_router
from app.routers.auth import router as auth_router


app = FastAPI(title="Code Analyzer API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
def startup_event() -> None:
    initialize_database()


app.include_router(analyze_router)
app.include_router(auth_router)
