from app.api.agents import router as agents_router
from app.api.executions import router as executions_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.core.config import settings
from app.core.observability import configure_logging, new_request_id, request_id_var
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

configure_logging(settings.log_level)
app = FastAPI(title=settings.app_name, version="0.4.0")
app.include_router(health_router, prefix="/api")
app.include_router(executions_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response
    except Exception:
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "request_id": request_id,
            },
        )
    finally:
        request_id_var.reset(token)


@app.get("/")
def root() -> dict:
    return {"service": "automation-engine", "version": "0.4.0", "status": "ok"}
