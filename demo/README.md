# Free local AI + n8n demo

This demo runs the Automation Engine with PostgreSQL, Redis, Ollama and n8n. No paid AI API key is required.

## Start

```bash
docker compose up -d --build
```

Pull the demo model once:

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

Open n8n at `http://localhost:5678`, import `demo/n8n/automation-engine-demo.json`, then activate the workflow.

The webhook path is:

```text
/webhook/automation-engine-demo
```

The Automation Engine is available at `http://localhost:8000`.

## Run an AI execution

Create an execution with an n8n webhook target:

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

The API returns an execution id. Run it with:

```bash
curl -X POST http://localhost:8000/api/executions/<EXECUTION_ID>/run
```

Then inspect the execution:

```bash
curl http://localhost:8000/api/executions/<EXECUTION_ID>
```

The successful output should contain `provider: "ollama"`, the generated `text`, and the n8n response.

## Important

The compose stack is intended for local development/demo use. Do not expose PostgreSQL, Redis, n8n or Ollama directly to the public internet without authentication and network controls.
