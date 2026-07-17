"""FastAPI application entrypoint for the hybrid C++ code-review backend.

Problem solved: this module wires together the routers, CORS and the startup
database initialisation, and exposes a ``/health`` probe. Why a single
``FastAPI`` app instance: it is what uvicorn serves and what the tests import.

Why permissive CORS: the existing mobile client and local frontend call this
API cross-origin; tighten ``allow_origins`` before any public deployment.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import initialize_database
from app.routers.analyze import router as analyze_router
from app.routers.auth import router as auth_router

app = FastAPI(title="Code Analyzer API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend, load balancer and tests.

    Problem solved: a cheap endpoint to confirm the process is up without
    touching the model or the database.

    :return: a status object.
    """
    return {"status": "ok"}


@app.on_event("startup")
def startup_event() -> None:
    """Create the database schema on process start.

    Problem solved: ensures tables exist before the first request. Why at
    startup (not lazily per-request): avoids repeated existence checks.

    :return: None.
    """
    initialize_database()


app.include_router(analyze_router)
app.include_router(auth_router)
