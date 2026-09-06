from html import escape

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.agents import router as agents_router
from app.api.executions import router as executions_router, orchestrator
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.core.config import settings
from app.core.observability import configure_logging, new_request_id, request_id_var
from app.models.execution import Execution

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
        if request.url.path == "/":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
    finally:
        request_id_var.reset(token)


@app.post("/demo/run", response_class=HTMLResponse)
async def demo_run(task: str = Form("")) -> str:
    task = task.strip()
    if not task:
        return demo_page("", "Please enter a task.", error=True)

    execution = Execution(workflow="demo", input={"message": task})
    await orchestrator.repository.save(execution)
    result = await orchestrator.process(str(execution.id))
    if result is None:
        return demo_page(task, "Execution not found.", error=True)

    if result.status.value == "succeeded":
        output = result.output or {}
        return demo_page(
            task,
            __import__("json").dumps(output, ensure_ascii=False, indent=2),
            meta=f"Execution ID: {result.id} · Status: {result.status.value} · Attempts: {result.attempts}",
        )

    details = {
        "status": result.status.value,
        "error": result.error,
        "output": result.output,
        "attempts": result.attempts,
    }
    return demo_page(
        task,
        __import__("json").dumps(details, ensure_ascii=False, indent=2),
        meta=f"Execution ID: {result.id} · Status: {result.status.value} · Attempts: {result.attempts}",
        error=True,
    )


def demo_page(task: str, result: str = "", meta: str = "", error: bool = False) -> str:
    result_html = escape(result)
    meta_html = escape(meta)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store">
<title>Automation Engine Demo</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,system-ui,sans-serif;background:#0b1020;color:#eef2ff;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}.card{{width:min(760px,100%);background:#121a2e;border:1px solid #263252;border-radius:24px;padding:32px;box-shadow:0 24px 70px #0008}}.badge{{display:inline-block;padding:7px 12px;border-radius:999px;background:#1d2947;color:#9fb7ff;font-size:13px;font-weight:700}}.title{{font-size:clamp(32px,7vw,56px);margin:18px 0 8px;letter-spacing:-2px}}.sub{{color:#aab5cf;margin:0 0 28px;line-height:1.6}}.label{{font-size:14px;color:#c7d2fe;font-weight:700;margin-bottom:9px}}textarea{{width:100%;min-height:140px;resize:vertical;background:#0b1224;color:#fff;border:1px solid #30405f;border-radius:14px;padding:16px;font:inherit;outline:none}}textarea:focus{{border-color:#6d8cff}}button{{width:100%;margin-top:14px;border:0;border-radius:14px;padding:15px;font-size:16px;font-weight:800;cursor:pointer;background:#6d8cff;color:white;touch-action:manipulation}}.status{{margin-top:24px;padding:18px;border-radius:14px;background:#0b1224;border:1px solid #263252}}.steps{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}}.step{{padding:7px 10px;border-radius:999px;background:#1a243b;color:#7f8ba8;font-size:12px}}.step.active{{background:#203a2b;color:#73e2a0}}.step.error{{background:#4a2027;color:#ff9ca8}}.result{{white-space:pre-wrap;color:#cbd5e1;line-height:1.55}}.meta{{font-size:12px;color:#7783a0;margin-top:12px;word-break:break-all}}.error{{color:#ff9ca8}}
</style></head>
<body><main class="card">
<span class="badge">AUTOMATION ENGINE · DEMO</span>
<h1 class="title">Automate a task.</h1>
<p class="sub">This demo uses a normal HTML form, so execution works even when browser JavaScript is unavailable.</p>
<form method="post" action="/demo/run">
<div class="label">YOUR TASK</div>
<textarea id="task" name="task">{escape(task)}</textarea>
<button id="run" type="submit">Execute Automation</button>
</form>
<div class="status">
<div class="steps"><span class="step active">RECEIVED</span><span class="step active">QUEUED</span><span class="step {"error" if error else "active"}">{"FAILED/RETRY" if error else "EXECUTED"}</span><span class="step {"error" if error else "active"}">{"ERROR" if error else "SUCCEEDED"}</span></div>
<div class="result {"error" if error else ""}">{result_html}</div>
<div class="meta">{meta_html}</div>
</div>
</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return demo_page("أرسل لي رسالة ترحيب للعميل أحمد")
