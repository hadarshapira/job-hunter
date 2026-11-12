from fastapi import FastAPI

import logging

from app import api, api_discovery, auth

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="JobHunter", version="0.2.0")
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(api_discovery.router)


@app.get("/api/health")
def health():
    return {"ok": True}
