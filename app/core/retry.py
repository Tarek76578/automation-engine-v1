from collections.abc import Callable
from time import sleep


def with_retry(operation: Callable[[], object], attempts: int = 3, delay_seconds: float = 0.25) -> object:
    """Execute an operation with bounded retries; preserve the final exception."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - orchestration boundary
            last_error = exc
            if attempt + 1 < attempts:
                sleep(delay_seconds * (2**attempt))
    assert last_error is not None
    raise last_error
