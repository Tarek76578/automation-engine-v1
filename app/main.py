from fastapi import FastAPI
from app.api.health import router as health_router

app = FastAPI(title="Automation Engine", version="0.1.0")
app.include_router(health_router, prefix="/api")

@app.get("/")
def root() -> dict:
    return {"service": "automation-engine", "version": "0.1.0", "status": "ok"}
