"""Bounded thread pool draining a capacity-limited FIFO job queue."""
from __future__ import annotations

import threading
from collections import deque


class ThreadPool:
    """Fixed worker set draining a bounded FIFO queue of jobs.

    Three condition variables share one lock: ``_not_empty`` for workers
    waiting on work, ``_not_full`` for producers waiting on capacity, and
    ``_done`` for callers waiting on results.
    """

    def __init__(self, workers: int = 2, max_jobs: int = 2) -> None:
        self.max_jobs = max_jobs
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)
        self._done = threading.Condition(self._lock)
        self._queue: deque[tuple[str, object, tuple]] = deque()
        self._results: dict[str, object] = {}
        self._waiting_producers = 0
        self._workers = [
            threading.Thread(target=self._work, name=f"pool-worker-{index}", daemon=True)
            for index in range(workers)
        ]
        for worker in self._workers:
            worker.start()

    @property
    def waiting_producers(self) -> int:
        """How many producers are blocked waiting for a free queue slot."""
        with self._not_full:
            return self._waiting_producers

    def submit(self, key: str, fn, args: tuple = ()) -> None:
        """Queue one job; blocks while the queue is at capacity."""
        with self._not_full:
            while len(self._queue) >= self.max_jobs:
                self._waiting_producers += 1
                try:
                    self._not_full.wait()
                finally:
                    self._waiting_producers -= 1
            self._queue.append((key, fn, args))
        with self._not_empty:
            self._not_empty.notify()

    def join_job(self, key: str, timeout: float = 5.0):
        """Return a job's result, or raise TimeoutError when it never runs."""
        with self._done:
            while key not in self._results:
                if not self._done.wait(timeout):
                    raise TimeoutError(f"job {key!r} never completed")
            return self._results[key]

    def _work(self) -> None:
        while True:
            with self._not_empty:
                while not self._queue:
                    self._not_empty.wait()
                key, fn, args = self._queue.popleft()
                # NOTE: the freed queue slot is never announced to producers.
            value = fn(*args)
            with self._done:
                self._results[key] = value
                self._done.notify_all()
