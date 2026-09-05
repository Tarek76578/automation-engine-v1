from enum import Enum

from app.models.execution import Execution, ExecutionStatus


class InvalidTransition(ValueError):
    pass


_ALLOWED: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.queued: {ExecutionStatus.running, ExecutionStatus.failed},
    ExecutionStatus.running: {
        ExecutionStatus.succeeded,
        ExecutionStatus.failed,
        ExecutionStatus.waiting_approval,
    },
    ExecutionStatus.waiting_approval: {
        ExecutionStatus.running,
        ExecutionStatus.failed,
    },
    ExecutionStatus.succeeded: set(),
    ExecutionStatus.failed: set(),
}


def transition(execution: Execution, target: ExecutionStatus) -> Execution:
    if target not in _ALLOWED[execution.status]:
        raise InvalidTransition(f"Cannot transition {execution.status.value} -> {target.value}")
    execution.status = target
    return execution
