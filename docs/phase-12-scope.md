# Phase 12 — Messenger Business Agent Memory

## Goal
Turn inbound Messenger events into a context-aware business agent without changing the existing approval and execution safety model.

## Scope
- Persist inbound/outbound Messenger conversation messages.
- Group messages by page + customer (`conversation_key`).
- Retrieve recent conversation context before planning.
- Include conversation context in the Agent Planner prompt.
- Persist the assistant reply after a successful Meta send.
- Keep duplicate webhook events idempotent.
- Keep outbound replies approval-gated by default; `META_MESSENGER_AUTO_REPLY=true` remains an explicit opt-in.
- Keep secrets and access tokens out of persisted conversation records.

## Non-goals
- No automatic ad spending.
- No automatic publishing outside the existing explicit actions.
- No Meta OAuth redesign.
- No claims of exactly-once delivery.
