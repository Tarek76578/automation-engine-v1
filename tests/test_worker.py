import asyncio
from uuid import uuid4

import pytest

from app.core.job_queue import Job


class FakeQueue:
    def __init__(self, job: Job) -> None:
        self.job = job
        self.acked: list[Job] = []
        self.recovered = 0
        self.dequeued = False

    async def recover(self) -> int:
        value = self.recovered
        self.recovered = 0
        return value

    async def dequeue(self) -> Job:
        if self.dequeued:
            raise asyncio.CancelledError
        self.dequeued = True
        return self.job

    async def ack(self, job: Job) -> None:
        self.acked.append(job)


@pytest.mark.asyncio
async def test_worker_processes_and_acks_job(monkeypatch) -> None:
    from app import worker

    job = Job(execution_id=uuid4())
    queue = FakeQueue(job)
    processed: list[str] = []

    async def process(execution_id: str):
        processed.append(execution_id)
        return type(
            "Result",
            (),
            {
                "id": job.execution_id,
                "status": type("Status", (), {"value": "succeeded"})(),
                "attempts": 1,
            },
        )()

    monkeypatch.setattr(worker, "queue", queue)
    monkeypatch.setattr(worker.orchestrator, "process", process)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_worker()

    assert processed == [str(job.execution_id)]
    assert queue.acked == [job]
