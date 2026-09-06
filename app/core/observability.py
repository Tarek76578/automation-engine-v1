from __future__ import annotations

import logging
from contextvars import ContextVar
from uuid import uuid4

from prometheus_client import Counter, Histogram

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s request_id=%(request_id)s "
            "%(name)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def new_request_id() -> str:
    return uuid4().hex


EXECUTIONS_TOTAL = Counter(
    "automation_executions_total",
    "Total execution attempts by workflow and outcome.",
    ["workflow", "status"],
)

EXECUTION_RETRIES_TOTAL = Counter(
    "automation_execution_retries_total",
    "Total execution retries scheduled.",
    ["workflow"],
)

ACTIONS_TOTAL = Counter(
    "automation_actions_total",
    "Total action execution attempts by action and outcome.",
    ["action", "status"],
)

EXECUTION_DURATION_SECONDS = Histogram(
    "automation_execution_duration_seconds",
    "Execution duration in seconds.",
    ["workflow", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

IDEMPOTENCY_HITS_TOTAL = Counter(
    "automation_idempotency_hits_total",
    "Executions returned because the idempotency key already existed.",
    ["workflow"],
)
