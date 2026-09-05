from fastapi import APIRouter
from prometheus_client import Counter, generate_latest
from starlette.responses import Response

router = APIRouter(tags=["observability"])

REQUESTS = Counter("automation_http_requests_total", "Total HTTP requests", ["method", "path"])


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type="text/plain; version=0.0.4")
