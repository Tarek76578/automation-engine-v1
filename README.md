# Automation Engine

Durable automation orchestration service with FastAPI, Redis, PostgreSQL, workers, and n8n integration.

## GitHub Codespaces demo (phone-friendly)

The `codespaces-demo` branch is prepared for a lightweight first integration test. **Ollama is intentionally disabled in this profile** so the first test does not require a large local model or GPU.

GitHub Codespaces runs the development environment on a remote VM, so your phone only acts as the client. GitHub personal accounts currently include 120 compute hours and 15 GB-month storage per month on the Free plan. Usage beyond the included quota is blocked when no payment method is configured. See GitHub's Codespaces billing documentation for the current limits.

### Start from Android

1. Open the repository on GitHub and switch to `codespaces-demo`.
2. Tap **Code → Codespaces → Create codespace on codespaces-demo**.
3. Wait for the Codespace to finish building. The repository contains `.devcontainer/devcontainer.json`, so Python and Docker-in-Docker are configured automatically.
4. In the Codespaces terminal run:

```bash
docker compose up -d --build
```

5. Check the stack:

```bash
docker compose ps
```

6. Test the API:

```bash
curl http://localhost:8000/api/health
```

Expected:

```json
{"status":"healthy"}
```

7. Test an end-to-end queued execution without an AI provider:

```bash
curl -X POST http://localhost:8000/api/executions \
  -H 'Content-Type: application/json' \
  -d '{"workflow":"codespaces-demo","input":{"prompt":"hello from Codespaces"}}'
```

Copy the returned `id`, then run it:

```bash
curl -X POST http://localhost:8000/api/executions/<ID>/run
```

The first test should prove the core path independently of Ollama: **FastAPI → PostgreSQL → Redis → worker/runtime → execution result**.

### n8n test

The bundled n8n demo workflow is imported automatically on first startup. Codespaces forwards port `5678`, so the n8n UI can be opened from the forwarded-port notification.

### Why Ollama is disabled here

The production/demo Compose configuration previously required Ollama to become healthy before the API and worker could start. That made the entire stack depend on downloading and loading a local LLM. The Codespaces branch removes that hard dependency for the first integration test. The runtime already supports an empty provider configuration and returns an accepted execution result when no LLM provider is configured.

Ollama can be reintroduced later as an optional profile after the core queue/orchestrator/n8n path is verified.
