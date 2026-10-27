"""
server_engine.py - Core execution engines demonstrating thread management.

Operating Systems Reference:
In high-performance web servers, incoming requests are queued and processed either
sequentially (baseline) or concurrently via a bounded pool of reusable worker threads.
Key OS concepts demonstrated:
1. Thread lifecycle & reuse: creating threads once and keeping them alive to avoid
   expensive context-switching and creation overhead.
2. Bounded FIFO Queue (Producer-Consumer): prevents unbounded memory consumption and
   applies explicit back-pressure/rejection when capacity is reached.
3. Synchronization: Lock primitives around shared metrics, condition variables inside
   Queue.put()/get(), and atomic counters.
4. Graceful shutdown: draining queued tasks or signaling worker termination cleanly.
"""

from __future__ import annotations
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional
from metrics import RunMetrics


class Task:
    """Represents a simulated web request."""
    def __init__(self, request_id: str, simulated_io_ms: float = 0.0, should_fail: bool = False) -> None:
        self.request_id = request_id
        self.simulated_io_ms = simulated_io_ms
        self.should_fail = should_fail
        self.created_at = time.perf_counter()


def execute_task(task: Task, worker_name: str, metrics: RunMetrics) -> None:
    """
    Shared request handler executed by both baseline and pool workers.
    NOTE: Locks are NOT held while sleeping or performing task work.
    """
    t_start = time.perf_counter()
    success = False
    error_msg = None

    try:
        # Simulate I/O wait (e.g., database query or remote API call)
        if task.simulated_io_ms > 0:
            time.sleep(task.simulated_io_ms / 1000.0)

        if task.should_fail:
            raise RuntimeError(f"Simulated internal error processing {task.request_id}")

        success = True
    except Exception as exc:
        success = False
        error_msg = str(exc)
    finally:
        t_end = time.perf_counter()
        latency_ms = (t_end - t_start) * 1000.0
        metrics.record_task_completion(
            request_id=task.request_id,
            success=success,
            latency_ms=latency_ms,
            worker_name=worker_name,
            error_msg=error_msg
        )


_SENTINEL = object()  # Poison pill for worker shutdown


class SequentialBaselineServer:
    """
    Sequential Baseline Engine (1 worker thread).
    Processes tasks one after another in order of arrival through a single-worker queue.
    Provides a direct performance baseline to compare against the bounded worker pool.
    """
    def __init__(self, metrics: RunMetrics, queue_capacity: int = 100) -> None:
        self.metrics = metrics
        self.queue_capacity = queue_capacity
        self.task_queue: queue.Queue = queue.Queue(maxsize=queue_capacity)
        self.worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._active_workers = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            name="BaselineWorker-1",
            daemon=True
        )
        self.worker_thread.start()

    def submit(self, task: Task) -> bool:
        """
        Submits task to the sequential worker. If queue is full, rejects immediately.
        """
        self.metrics.record_attempt()
        try:
            # Non-blocking submission: fail immediately if queue is full
            self.task_queue.put_nowait(task)
            self.metrics.record_accepted()
            self.metrics.update_queue_depth(self.task_queue.qsize())
            return True
        except queue.Full:
            self.metrics.record_rejection(task.request_id, reason="Queue full (baseline)")
            return False

    def _worker_loop(self) -> None:
        while self._running:
            try:
                item = self.task_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is _SENTINEL:
                self.task_queue.task_done()
                break

            with self._lock:
                self._active_workers = 1
                self.metrics.update_active_workers(1)

            try:
                execute_task(item, "BaselineWorker-1", self.metrics)
            finally:
                with self._lock:
                    self._active_workers = 0
                self.task_queue.task_done()
                self.metrics.update_queue_depth(self.task_queue.qsize())

    def get_active_worker_count(self) -> int:
        with self._lock:
            return self._active_workers

    def get_queue_depth(self) -> int:
        return self.task_queue.qsize()

    def wait_completion(self) -> None:
        """Blocks until all accepted tasks in the queue have called task_done()."""
        self.task_queue.join()

    def shutdown(self, drain: bool = True) -> None:
        """Stops the worker thread safely without leaving orphaned threads."""
        if not self._running:
            return
        if drain:
            self.wait_completion()
        self._running = False
        try:
            self.task_queue.put(_SENTINEL, timeout=0.5)
        except queue.Full:
            pass
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)


class BoundedThreadPoolServer:
    """
    Bounded Thread Pool Server Engine.
    Implements a fixed pool of pre-spawned worker threads consuming tasks from a
    bounded FIFO queue (Producer-Consumer architecture).
    """
    def __init__(self, metrics: RunMetrics, worker_count: int = 8, queue_capacity: int = 100) -> None:
        self.metrics = metrics
        self.worker_count = max(1, min(32, worker_count))
        self.queue_capacity = max(1, min(2000, queue_capacity))
        self.task_queue: queue.Queue = queue.Queue(maxsize=self.queue_capacity)
        self.workers: list[threading.Thread] = []
        self._running = False
        self._active_workers = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        for i in range(1, self.worker_count + 1):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"PoolWorker-{i}",
                daemon=True
            )
            self.workers.append(worker)
            worker.start()

    def submit(self, task: Task) -> bool:
        """
        Submits task to the bounded pool queue.
        If queue is at capacity, rejects with back-pressure immediately.
        """
        self.metrics.record_attempt()
        try:
            self.task_queue.put_nowait(task)
            self.metrics.record_accepted()
            self.metrics.update_queue_depth(self.task_queue.qsize())
            return True
        except queue.Full:
            self.metrics.record_rejection(task.request_id, reason="Queue full (bounded pool)")
            return False

    def _worker_loop(self) -> None:
        worker_name = threading.current_thread().name
        while self._running:
            try:
                item = self.task_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is _SENTINEL:
                self.task_queue.task_done()
                break

            with self._lock:
                self._active_workers += 1
                self.metrics.update_active_workers(self._active_workers)

            try:
                execute_task(item, worker_name, self.metrics)
            finally:
                with self._lock:
                    self._active_workers = max(0, self._active_workers - 1)
                self.task_queue.task_done()
                self.metrics.update_queue_depth(self.task_queue.qsize())

    def get_active_worker_count(self) -> int:
        with self._lock:
            return self._active_workers

    def get_queue_depth(self) -> int:
        return self.task_queue.qsize()

    def wait_completion(self) -> None:
        """Blocks until all accepted tasks in the queue are processed."""
        self.task_queue.join()

    def shutdown(self, drain: bool = True) -> None:
        """
        Signals all workers to stop and joins each worker thread.
        Guarantees no orphaned threads.
        """
        if not self._running:
            return
        if drain:
            self.wait_completion()
        self._running = False

        # Send one sentinel poison pill per worker
        for _ in self.workers:
            try:
                self.task_queue.put(_SENTINEL, timeout=0.1)
            except queue.Full:
                pass

        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=2.0)
        self.workers.clear()
