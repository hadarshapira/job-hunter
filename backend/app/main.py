"""FastAPI app: wires the routers together. Run by uvicorn in the "api" container (see backend/Dockerfile)."""

import logging

from fastapi import FastAPI

from app import api, api_discovery, api_gmail, api_profile, auth

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="JobHunter", version="0.2.0")
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(api_discovery.router)
app.include_router(api_profile.router)
app.include_router(api_gmail.router)


@app.get("/api/health")
def health():
    return {"ok": True}
