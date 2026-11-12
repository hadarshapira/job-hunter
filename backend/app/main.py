from fastapi import FastAPI

from app import api, auth

app = FastAPI(title="JobHunter", version="0.1.0")
app.include_router(auth.router)
app.include_router(api.router)


@app.get("/api/health")
def health():
    return {"ok": True}
