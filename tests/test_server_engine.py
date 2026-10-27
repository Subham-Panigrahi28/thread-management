"""
test_server_engine.py - Unit tests for baseline and bounded thread pool engines.
Covers Section 8 minimum tests:
3. Baseline processes tasks and records outcomes.
4. Pool processes tasks with multiple workers.
5. Queue-full case counts rejections without hanging.
6. One task exception does not kill all workers.
11. Graceful shutdown leaves no worker threads alive.
"""

import time
import unittest
from metrics import RunMetrics
from server_engine import BoundedThreadPoolServer, SequentialBaselineServer, Task


class TestServerEngine(unittest.TestCase):
    def test_baseline_processes_tasks(self):
        """Test 3: Baseline processes tasks sequentially and records outcomes."""
        metrics = RunMetrics("test-base", "baseline", {})
        metrics.start()
        server = SequentialBaselineServer(metrics=metrics, queue_capacity=10)
        server.start()

        for i in range(5):
            accepted = server.submit(Task(request_id=f"t-{i}", simulated_io_ms=0))
            self.assertTrue(accepted)

        server.wait_completion()
        metrics.stop()
        server.shutdown(drain=True)

        snap = metrics.snapshot()
        self.assertEqual(snap["attempted"], 5)
        self.assertEqual(snap["accepted"], 5)
        self.assertEqual(snap["successful"], 5)
        self.assertEqual(snap["rejected"], 0)
        self.assertIsNotNone(snap["avg_latency_ms"])

    def test_pool_processes_tasks_with_multiple_workers(self):
        """Test 4: Pool processes tasks concurrently with multiple workers."""
        metrics = RunMetrics("test-pool", "bounded_pool", {})
        metrics.start()
        server = BoundedThreadPoolServer(metrics=metrics, worker_count=4, queue_capacity=20)
        server.start()
        self.assertEqual(len(server.workers), 4)

        for i in range(8):
            accepted = server.submit(Task(request_id=f"t-{i}", simulated_io_ms=5))
            self.assertTrue(accepted)

        server.wait_completion()
        metrics.stop()
        server.shutdown(drain=True)

        snap = metrics.snapshot()
        self.assertEqual(snap["attempted"], 8)
        self.assertEqual(snap["successful"], 8)
        self.assertGreaterEqual(snap["max_active_workers"], 1)

    def test_queue_full_rejections_without_hanging(self):
        """Test 5: Queue-full case counts rejections without deadlock or hanging."""
        # Use queue capacity 1 and hold worker busy with a task
        metrics = RunMetrics("test-overflow", "bounded_pool", {})
        metrics.start()
        # 1 worker, 1 queue slot
        server = BoundedThreadPoolServer(metrics=metrics, worker_count=1, queue_capacity=1)
        server.start()

        # Task 1 takes the 1 worker
        server.submit(Task(request_id="task-busy", simulated_io_ms=100))
        # Wait until worker picks up task-busy so queue has space for 1 task
        deadline = time.time() + 1.0
        while server.get_active_worker_count() == 0 and time.time() < deadline:
            time.sleep(0.005)

        # Task 2 fills the 1 slot in the queue
        t2_accepted = server.submit(Task(request_id="task-slot-1", simulated_io_ms=10))
        self.assertTrue(t2_accepted, "Task 2 should be accepted into the 1 queue slot")

        # Task 3 should exceed capacity and immediately be rejected without hanging
        t3_accepted = server.submit(Task(request_id="task-overflow", simulated_io_ms=10))
        self.assertFalse(t3_accepted, "Task 3 must be rejected because queue is at capacity")

        server.wait_completion()
        metrics.stop()
        server.shutdown(drain=True)

        snap = metrics.snapshot()
        self.assertEqual(snap["attempted"], 3)
        self.assertEqual(snap["rejected"], 1)
        self.assertEqual(snap["successful"], 2)

    def test_one_task_exception_does_not_kill_all_workers(self):
        """Test 6: Exception in one task records as failure but workers survive."""
        metrics = RunMetrics("test-err", "bounded_pool", {})
        metrics.start()
        server = BoundedThreadPoolServer(metrics=metrics, worker_count=2, queue_capacity=10)
        server.start()

        # Submit task designed to fail
        server.submit(Task(request_id="task-bad", should_fail=True))
        # Submit subsequent normal tasks
        server.submit(Task(request_id="task-ok-1", should_fail=False))
        server.submit(Task(request_id="task-ok-2", should_fail=False))

        server.wait_completion()
        metrics.stop()
        server.shutdown(drain=True)

        snap = metrics.snapshot()
        self.assertEqual(snap["attempted"], 3)
        self.assertEqual(snap["failed"], 1)
        self.assertEqual(snap["successful"], 2)

    def test_graceful_shutdown_leaves_no_worker_threads_alive(self):
        """Test 11: Graceful shutdown cleanly terminates all worker threads."""
        metrics = RunMetrics("test-shutdown", "bounded_pool", {})
        server = BoundedThreadPoolServer(metrics=metrics, worker_count=4, queue_capacity=10)
        server.start()

        worker_threads = list(server.workers)
        for w in worker_threads:
            self.assertTrue(w.is_alive())

        # Trigger graceful shutdown
        server.shutdown(drain=False)

        for w in worker_threads:
            self.assertFalse(w.is_alive(), f"Worker {w.name} was not shut down cleanly.")


if __name__ == "__main__":
    unittest.main()
