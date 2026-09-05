# Automation Engine V1

Production-oriented AI automation and orchestration platform.

## Architecture

- FastAPI control plane
- Agent runtime and registry
- Provider-neutral LLM routing with an OpenAI adapter
- Execution state machine
- Production execution orchestrator
- n8n webhook integration boundary
- Async job queue with in-memory and Redis adapters
- Execution repository with in-memory and PostgreSQL adapters
- Request correlation IDs, structured logging, and Prometheus metrics
- Docker and GitHub Actions CI

## Execution flow

`API -> Persistence -> Queue -> Worker -> Agent -> LLM -> n8n -> Persistence`

Executions support idempotency keys, attempt tracking, bounded retries, terminal failure states, and timezone-aware timestamps. External integrations remain injectable so the core flow can be tested without credentials.

## Development status

- Phase 1 — service foundation
- Phase 2 — execution and routing contracts
- Phase 3 — agent runtime and integration boundaries
- Phase 4 — production orchestrator and execution lifecycle
- Next — durable worker process, authentication/audit, database migrations, and deeper provider/tool orchestration
