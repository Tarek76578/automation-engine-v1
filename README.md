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
- Redis crash recovery with processing-list acknowledgement
- Exponential retry backoff and Redis delayed jobs
- Dead-letter queue for terminal execution failures
- Execution repository with in-memory and PostgreSQL adapters
- Alembic database migrations
- Request correlation IDs, structured logging, and Prometheus metrics
- Docker and GitHub Actions CI

## Execution flow

`API -> Persistence -> Queue -> Worker -> Agent -> LLM -> n8n -> Persistence`

Executions support idempotency keys, attempt tracking, bounded retries, exponential backoff, terminal failure states, and timezone-aware timestamps. External integrations remain injectable so the core flow can be tested without credentials.

## Production queue semantics

Redis uses a pending list plus a processing list. A worker claims a job atomically into the processing list and acknowledges it only after the execution completes. Jobs left in the processing list can be recovered when a worker restarts. Terminal failures are removed from processing and written to a Redis dead-letter list.

Retry jobs use a Redis sorted set for delayed delivery and are promoted when their scheduled time is reached.

## Database migrations

Alembic migrations live under `migrations/`.

With `DATABASE_URL` configured, initialize or upgrade the database with:

```bash
alembic upgrade head
```

The application retains schema bootstrap compatibility for local development, while Alembic is the canonical migration path for deployments.

## Development status

- Phase 1 — service foundation
- Phase 2 — execution and routing contracts
- Phase 3 — agent runtime and integration boundaries
- Phase 4 — production orchestrator and execution lifecycle
- Phase 4 Hardening V2 — durable queue acknowledgement/recovery, retry backoff, DLQ, and Alembic
- Next — authentication/audit, durable worker process lifecycle, provider/tool orchestration, and workflow graphs
