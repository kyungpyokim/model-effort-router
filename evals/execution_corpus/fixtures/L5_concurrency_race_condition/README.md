# taskpool

Bounded thread pool draining a FIFO job queue.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L5_concurrency_race_condition (implementation, L5)
- Task: Fix intermittent race condition causing deadlocks in thread pool queue
- Expected initial test outcome: FAIL (pytest exit status 1)
- The acceptance checks use bounded waits, so the initial lost-wakeup defect
  surfaces as a deterministic failure instead of a hang: a producer blocked at
  queue capacity is never woken when workers free slots, and the over-capacity
  check fails after its timeout. After the hand-off is fixed, every submitted
  job completes with the correct result.

## Contracts

- `ThreadPool(workers, max_jobs)` starts `workers` daemon workers draining a
  FIFO queue capped at `max_jobs` entries.
- `submit(key, fn, args)` queues a job; while the queue is at capacity it
  blocks until a worker frees a slot — and that freed slot must wake at least
  one blocked producer (missing wake-up = the queue race/deadlock).
- `join_job(key, timeout)` returns the job's result or raises `TimeoutError`
  when the job never completes within the timeout.
- `waiting_producers` reports how many producers are currently blocked waiting
  for a free queue slot (used by the acceptance test to observe the hand-off).
- Workers store results under the job key and wake result waiters; job order
  is FIFO.
