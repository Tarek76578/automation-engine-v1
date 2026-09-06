from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.agents import router as agents_router
from app.api.executions import router as executions_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.core.config import settings
from app.core.observability import configure_logging, new_request_id, request_id_var

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


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Automation Engine Demo v5</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;background:#0b1020;color:#eef2ff;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}.card{width:min(760px,100%);background:#121a2e;border:1px solid #263252;border-radius:24px;padding:32px;box-shadow:0 24px 70px #0008}.badge{display:inline-block;padding:7px 12px;border-radius:999px;background:#1d2947;color:#9fb7ff;font-size:13px;font-weight:700}.title{font-size:clamp(32px,7vw,56px);margin:18px 0 8px;letter-spacing:-2px}.sub{color:#aab5cf;margin:0 0 28px;line-height:1.6}.label{font-size:14px;color:#c7d2fe;font-weight:700;margin-bottom:9px}textarea{width:100%;min-height:140px;resize:vertical;background:#0b1224;color:#fff;border:1px solid #30405f;border-radius:14px;padding:16px;font:inherit;outline:none}textarea:focus{border-color:#6d8cff}button{width:100%;margin-top:14px;border:0;border-radius:14px;padding:15px;font-size:16px;font-weight:800;cursor:pointer;background:#6d8cff;color:white;touch-action:manipulation;-webkit-tap-highlight-color:transparent}button:disabled{opacity:.55;cursor:wait}.status{margin-top:24px;padding:18px;border-radius:14px;background:#0b1224;border:1px solid #263252;display:none}.steps{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.step{padding:7px 10px;border-radius:999px;background:#1a243b;color:#7f8ba8;font-size:12px}.step.active{background:#203a2b;color:#73e2a0}.step.error{background:#4a2027;color:#ff9ca8}.result{white-space:pre-wrap;color:#cbd5e1;line-height:1.55}.meta{font-size:12px;color:#7783a0;margin-top:12px;word-break:break-all}.error{color:#ff9ca8}a{color:#9fb7ff}
</style></head>
<body><main class="card">
<span class="badge">AUTOMATION ENGINE · DEMO v5</span>
<h1 class="title">Automate a task.</h1>
<p class="sub">Describe what you want the automation engine to execute. The demo creates an execution, runs it, and shows the result.</p>
<div class="label">YOUR TASK</div>
<textarea id="task">أرسل لي رسالة ترحيب للعميل أحمد</textarea>
<button id="run" type="button" onclick="runTask()">Execute Automation</button>
<section class="status" id="status"><div class="steps"><span class="step" id="s1">RECEIVED</span><span class="step" id="s2">QUEUED</span><span class="step" id="s3">EXECUTING</span><span class="step" id="s4">SUCCEEDED</span></div><div class="result" id="result"></div><div class="meta" id="meta"></div></section>
</main>
<script>
const $=id=>document.getElementById(id);
function step(n,error=false){for(let i=1;i<=4;i++){const e=$("s"+i);e.classList.toggle("active",!error&&i<=n);e.classList.toggle("error",error&&i===n)}}
async function readResponse(response){const text=await response.text();let data;try{data=JSON.parse(text)}catch{data={detail:text}}if(!response.ok){throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data))}return data}
async function runTask(){const b=$("run"),st=$("status"),r=$("result"),m=$("meta"),task=$("task").value.trim();st.style.display="block";r.className="result";r.textContent="Starting automation…";m.textContent="Demo v5 is responding.";if(!task){r.className="result error";r.textContent="Please enter a task.";return}b.disabled=true;step(1);try{const created=await readResponse(await fetch('/api/executions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workflow:'demo',input:{message:task}})}));step(2);r.textContent="Execution queued. Running…";m.textContent="Execution ID: "+created.id;await new Promise(x=>setTimeout(x,350));step(3);const done=await readResponse(await fetch('/api/executions/'+created.id+'/run',{method:'POST'}));if(done.status==='succeeded'){step(4);r.textContent=JSON.stringify(done.output,null,2)}else{step(3,true);r.className='result error';r.textContent="Execution did not succeed.\n\n"+JSON.stringify({status:done.status,error:done.error,output:done.output,attempts:done.attempts},null,2)}m.textContent="Execution ID: "+done.id+" · Status: "+done.status+" · Attempts: "+done.attempts}catch(e){step(3,true);r.className='result error';r.textContent="Automation failed: "+e.message}finally{b.disabled=false}}
</script></body></html>"""
