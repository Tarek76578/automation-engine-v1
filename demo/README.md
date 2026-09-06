# Free local AI + n8n demo

This demo runs the Automation Engine with PostgreSQL, Redis, Ollama and n8n. No paid AI API key is required.

## Start

```bash
git clone https://github.com/Tarek76578/automation-engine-v1.git
cd automation-engine-v1
git checkout phase-4-hardening-v3
docker compose up -d --build
```

The stack now automatically:

- starts PostgreSQL and Redis;
- starts Ollama and pulls `llama3.2:3b` if it is not already present;
- imports the demo n8n workflow on first startup;
- starts a dedicated execution worker connected to Redis.

Open:

- Automation Engine: `http://localhost:8000`
- Health: `http://localhost:8000/api/health`
- n8n: `http://localhost:5678`

## Run the real demo

Create an execution. Do not call `/run`: the worker consumes the Redis job automatically.

```bash
curl -X POST http://localhost:8000/api/executions \
  -H 'Content-Type: application/json' \
  -d '{
    "workflow":"automation",
    "input":{
      "prompt":"Give me three concise steps for automating a customer support workflow.",
      "n8n_webhook":"webhook/automation-engine-demo"
    }
  }'
```

The API returns an execution id. Wait a few seconds, then inspect it:

```bash
curl http://localhost:8000/api/executions/<EXECUTION_ID>
```

A successful result contains the Ollama provider/model, generated AI text, and the n8n response.

## Verify the services

```bash
docker compose ps
docker compose logs --tail=100 worker
```

The intended flow is:

`HTTP request → Automation Engine → Redis → Worker → Ollama → n8n webhook → persisted execution result`

## Reset the demo

To remove the demo data and force a fresh model/workflow initialization:

```bash
docker compose down -v
docker compose up -d --build
```

The compose stack is intended for local development/demo use. Do not expose PostgreSQL, Redis, n8n or Ollama directly to the public internet without authentication and network controls.
