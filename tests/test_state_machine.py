from app.core.state_machine import InvalidTransition, transition
from app.models.execution import Execution, ExecutionStatus

import pytest


def test_valid_transition() -> None:
    execution = Execution(workflow="demo")
    transition(execution, ExecutionStatus.running)
    assert execution.status is ExecutionStatus.running


def test_terminal_transition_is_rejected() -> None:
    execution = Execution(workflow="demo", status=ExecutionStatus.succeeded)
    with pytest.raises(InvalidTransition):
        transition(execution, ExecutionStatus.running)
