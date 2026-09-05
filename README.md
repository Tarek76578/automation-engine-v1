# Automation Engine V1

Production-oriented AI automation and orchestration platform.

## Architecture

- FastAPI control plane
- Agent runtime and registry
- Provider-neutral LLM routing with an OpenAI adapter
- Execution state machine
- n8n webhook integration boundary
- Async job queue with in-memory and Redis adapters
- Execution repository with in-memory and PostgreSQL adapters
- Request correlation IDs, structured logging, and Prometheus metrics
- Docker and GitHub Actions CI

## Development status

- Phase 1 — service foundation
- Phase 2 — execution and routing contracts
- Phase 3 — agent runtime and orchestration foundations
- Current — persistence, queue, worker, provider, and observability adapters

External services are optional during local unit testing; reference adapters keep the core runtime testable without credentials.
