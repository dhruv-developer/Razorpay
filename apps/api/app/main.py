from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.cache import connect_redis, disconnect_redis
from app.config import get_settings
from app.db import connect, disconnect
from app.routers import actions, admin, agents, auth, copilot, events, merchant, ops, simulations
from app.seed.generator import seed_if_needed


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect()
    await connect_redis()
    await seed_if_needed()
    yield
    await disconnect_redis()
    await disconnect()


settings = get_settings()
app = FastAPI(
    title="Razorpay Business Brain",
    description="Shared merchant intelligence, simulation, and safety plane for Razorpay agents.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(events.router)
app.include_router(merchant.router)
app.include_router(simulations.router)
app.include_router(actions.router)
app.include_router(agents.router)
app.include_router(copilot.router)
app.include_router(admin.router)
app.include_router(ops.router)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "business-brain"}
