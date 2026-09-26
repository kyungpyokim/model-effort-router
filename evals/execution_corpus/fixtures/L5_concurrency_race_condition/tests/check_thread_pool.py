"""Acceptance checks: bounded pool must complete every submitted job."""
from __future__ import annotations

import threading
import time

from thread_pool import ThreadPool


def test_jobs_at_capacity_complete_with_results() -> None:
    pool = ThreadPool(workers=2, max_jobs=2)
    pool.submit("a", lambda: 2 * 21)
    pool.submit("b", lambda: "ok")
    assert pool.join_job("a", timeout=5) == 42
    assert pool.join_job("b", timeout=5) == "ok"


def test_workers_run_jobs_on_pool_threads() -> None:
    pool = ThreadPool(workers=2, max_jobs=2)
    pool.submit("who", lambda: threading.current_thread().name)
    name = pool.join_job("who", timeout=5)
    assert name.startswith("pool-worker-"), f"job ran on {name!r}"


def _await_blocked_producer(pool: ThreadPool) -> None:
    """Wait until a producer is provably blocked at queue capacity."""
    deadline = time.monotonic() + 5
    while pool.waiting_producers < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pool.waiting_producers >= 1, (
        "a submission made at full capacity must block a producer"
    )


def test_jobs_beyond_queue_capacity_still_complete() -> None:
    """Deterministically force the producer/worker hand-off race.

    Two gated jobs pin both workers so the queue can be filled to capacity;
    a fifth submission is then made from a helper thread and is confirmed
    blocked before the gate opens. Releasing the gate lets the workers drain
    the queue, so a correct pool hands the freed slots to the blocked producer
    and every job completes. The initial lost-wakeup state never notifies the
    capacity condition, which the bounded join turns into a clean failure.
    """
    pool = ThreadPool(workers=2, max_jobs=2)
    gate = threading.Event()
    both_workers_started = threading.Barrier(3, timeout=10)

    def gated(label: str):
        def job():
            both_workers_started.wait()
            gate.wait(timeout=10)
            return label

        return job

    try:
        pool.submit("job1", gated("one"))
        pool.submit("job2", gated("two"))
        both_workers_started.wait()

        pool.submit("job3", lambda: "three")
        pool.submit("job4", lambda: "four")

        producer = threading.Thread(
            target=lambda: pool.submit("job5", lambda: "five"), daemon=True
        )
        producer.start()
        _await_blocked_producer(pool)

        gate.set()
        producer.join(timeout=3)
        assert not producer.is_alive(), (
            "a queue slot freed by a worker must wake a producer blocked at capacity"
        )

        expected = {
            "job1": "one",
            "job2": "two",
            "job3": "three",
            "job4": "four",
            "job5": "five",
        }
        for key, value in expected.items():
            assert pool.join_job(key, timeout=5) == value, f"wrong result for {key}"
    finally:
        gate.set()
