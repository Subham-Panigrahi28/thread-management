"""
benchmark.py - Asynchronous benchmark coordinator and load generator.

Operating Systems Reference:
Load generation simulates multiple concurrent clients (producers) generating
requests for the server (consumer). Using a bounded producer pool models realistic
client connections without exhausting host OS thread resources.
"""

from __future__ import annotations
import concurrent.futures
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from metrics import RunMetrics, get_system_resource_snapshot
from server_engine import BoundedThreadPoolServer, SequentialBaselineServer, Task


class BenchmarkManager:
    """
    Manages active and completed benchmarks.
    Thread-safe coordinator for single-run and comparison workflows.
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.is_running: bool = False
        self.current_task_type: Optional[str] = None  # "single" or "compare"
        self.current_engine_name: Optional[str] = None
        self.current_engine: Optional[Any] = None
        self.current_metrics: Optional[RunMetrics] = None
        self.progress_message: str = "Ready"

        # Stored results
        self.latest_single_result: Optional[Dict[str, Any]] = None
        self.latest_comparison: Optional[Dict[str, Any]] = None
        self.all_completed_runs: List[Dict[str, Any]] = []

    def get_status(self) -> Dict[str, Any]:
        """Provides a real-time status update for the UI polling loop."""
        with self._lock:
            running = self.is_running
            active_engine = self.current_engine
            active_metrics = self.current_metrics
            progress = self.progress_message
            task_type = self.current_task_type
            engine_name = self.current_engine_name

        queue_depth = 0
        active_workers = 0
        metrics_snapshot = None

        if active_engine is not None:
            try:
                queue_depth = active_engine.get_queue_depth()
                active_workers = active_engine.get_active_worker_count()
            except Exception:
                pass

        if active_metrics is not None:
            metrics_snapshot = active_metrics.snapshot()

        return {
            "is_running": running,
            "task_type": task_type,
            "engine_name": engine_name,
            "progress_message": progress,
            "queue_depth": queue_depth,
            "active_workers": active_workers,
            "active_metrics": metrics_snapshot,
            "system_resources": get_system_resource_snapshot(),
            "has_latest_comparison": self.latest_comparison is not None,
            "has_latest_single": self.latest_single_result is not None
        }

    def start_single_benchmark(
        self,
        mode: str,
        request_count: int,
        producer_concurrency: int,
        worker_count: int,
        queue_capacity: int,
        simulated_io_ms: float
    ) -> Tuple[bool, str]:
        """Starts a single benchmark run in a background daemon thread."""
        with self._lock:
            if self.is_running:
                return False, "A benchmark is already running. Please wait for it to complete."
            self.is_running = True
            self.current_task_type = "single"
            self.progress_message = f"Starting {mode} benchmark..."

        worker_thread = threading.Thread(
            target=self._run_single_worker,
            args=(mode, request_count, producer_concurrency, worker_count, queue_capacity, simulated_io_ms),
            daemon=True
        )
        worker_thread.start()
        return True, "Benchmark started successfully."

    def start_comparison(
        self,
        request_count: int,
        producer_concurrency: int,
        worker_count: int,
        queue_capacity: int,
        simulated_io_ms: float
    ) -> Tuple[bool, str]:
        """Starts a fair, sequential comparison run (Baseline then Thread Pool)."""
        with self._lock:
            if self.is_running:
                return False, "A benchmark is already running. Please wait for it to complete."
            self.is_running = True
            self.current_task_type = "compare"
            self.progress_message = "Starting fair comparison (Sequential Baseline vs Bounded Thread Pool)..."

        worker_thread = threading.Thread(
            target=self._run_compare_worker,
            args=(request_count, producer_concurrency, worker_count, queue_capacity, simulated_io_ms),
            daemon=True
        )
        worker_thread.start()
        return True, "Comparison started successfully."

    def _execute_workload(
        self,
        engine: Any,
        metrics: RunMetrics,
        request_count: int,
        producer_concurrency: int,
        simulated_io_ms: float
    ) -> None:
        """
        Executes workload using a bounded producer pool to simulate concurrent clients.
        Each client thread submits requests into the engine's bounded queue.
        """
        metrics.start()
        engine.start()

        def producer_worker(task_id: int) -> None:
            req_id = f"req-{task_id:04d}"
            task = Task(request_id=req_id, simulated_io_ms=simulated_io_ms)
            engine.submit(task)

        # Producer pool simulates concurrent incoming HTTP connections
        with concurrent.futures.ThreadPoolExecutor(max_workers=producer_concurrency, thread_name_prefix="ClientProducer") as producer_pool:
            futures = [producer_pool.submit(producer_worker, i) for i in range(1, request_count + 1)]
            concurrent.futures.wait(futures)

        # Wait for all submitted work to be completely processed by the server
        engine.wait_completion()
        metrics.stop()
        engine.shutdown(drain=True)

    def _run_single_worker(
        self,
        mode: str,
        request_count: int,
        producer_concurrency: int,
        worker_count: int,
        queue_capacity: int,
        simulated_io_ms: float
    ) -> None:
        try:
            run_id = f"run-{uuid.uuid4().hex[:8]}"
            config = {
                "mode": mode,
                "request_count": request_count,
                "producer_concurrency": producer_concurrency,
                "worker_count": 1 if mode == "baseline" else worker_count,
                "queue_capacity": queue_capacity,
                "simulated_io_ms": simulated_io_ms
            }
            metrics = RunMetrics(run_id=run_id, mode=mode, config=config)

            if mode == "baseline":
                engine = SequentialBaselineServer(metrics=metrics, queue_capacity=queue_capacity)
                engine_name = "Sequential Baseline (1 worker)"
            else:
                engine = BoundedThreadPoolServer(metrics=metrics, worker_count=worker_count, queue_capacity=queue_capacity)
                engine_name = f"Bounded Thread Pool ({worker_count} workers)"

            with self._lock:
                self.current_metrics = metrics
                self.current_engine = engine
                self.current_engine_name = engine_name
                self.progress_message = f"Executing {engine_name} with {request_count} requests..."

            self._execute_workload(engine, metrics, request_count, producer_concurrency, simulated_io_ms)

            result = metrics.snapshot()
            with self._lock:
                self.latest_single_result = result
                self.all_completed_runs.append(result)
                self.progress_message = f"Completed {engine_name} successfully."
        except Exception as exc:
            with self._lock:
                self.progress_message = f"Error during benchmark: {exc}"
        finally:
            with self._lock:
                self.is_running = False
                self.current_engine = None
                self.current_task_type = None

    def _run_compare_worker(
        self,
        request_count: int,
        producer_concurrency: int,
        worker_count: int,
        queue_capacity: int,
        simulated_io_ms: float
    ) -> None:
        try:
            # Phase 1: Sequential Baseline (1 worker)
            with self._lock:
                self.progress_message = f"Phase 1/2: Running Sequential Baseline (1 worker) for {request_count} requests..."
                self.current_engine_name = "Sequential Baseline (1 worker)"

            run_id_base = f"cmp-base-{uuid.uuid4().hex[:6]}"
            config_base = {
                "mode": "baseline",
                "request_count": request_count,
                "producer_concurrency": producer_concurrency,
                "worker_count": 1,
                "queue_capacity": queue_capacity,
                "simulated_io_ms": simulated_io_ms
            }
            metrics_base = RunMetrics(run_id=run_id_base, mode="baseline", config=config_base)
            engine_base = SequentialBaselineServer(metrics=metrics_base, queue_capacity=queue_capacity)

            with self._lock:
                self.current_metrics = metrics_base
                self.current_engine = engine_base

            self._execute_workload(engine_base, metrics_base, request_count, producer_concurrency, simulated_io_ms)
            baseline_result = metrics_base.snapshot()

            # Short cooldown between phases
            time.sleep(0.5)

            # Phase 2: Bounded Thread Pool
            with self._lock:
                self.progress_message = f"Phase 2/2: Running Bounded Thread Pool ({worker_count} workers) for {request_count} requests..."
                self.current_engine_name = f"Bounded Thread Pool ({worker_count} workers)"

            run_id_pool = f"cmp-pool-{uuid.uuid4().hex[:6]}"
            config_pool = {
                "mode": "bounded_pool",
                "request_count": request_count,
                "producer_concurrency": producer_concurrency,
                "worker_count": worker_count,
                "queue_capacity": queue_capacity,
                "simulated_io_ms": simulated_io_ms
            }
            metrics_pool = RunMetrics(run_id=run_id_pool, mode="bounded_pool", config=config_pool)
            engine_pool = BoundedThreadPoolServer(metrics=metrics_pool, worker_count=worker_count, queue_capacity=queue_capacity)

            with self._lock:
                self.current_metrics = metrics_pool
                self.current_engine = engine_pool

            self._execute_workload(engine_pool, metrics_pool, request_count, producer_concurrency, simulated_io_ms)
            pool_result = metrics_pool.snapshot()

            # Comparison calculation
            speedup = None
            if baseline_result["duration_seconds"] > 0 and pool_result["duration_seconds"] > 0:
                speedup = round(baseline_result["duration_seconds"] / pool_result["duration_seconds"], 2)

            throughput_ratio = None
            if baseline_result["throughput_req_per_sec"] > 0:
                throughput_ratio = round(pool_result["throughput_req_per_sec"] / baseline_result["throughput_req_per_sec"], 2)

            comparison_summary = {
                "comparison_id": f"comp-{uuid.uuid4().hex[:8]}",
                "timestamp": round(time.time(), 3),
                "settings": {
                    "request_count": request_count,
                    "producer_concurrency": producer_concurrency,
                    "worker_count": worker_count,
                    "queue_capacity": queue_capacity,
                    "simulated_io_ms": simulated_io_ms
                },
                "baseline": baseline_result,
                "bounded_pool": pool_result,
                "duration_speedup": speedup,
                "throughput_ratio": throughput_ratio
            }

            with self._lock:
                self.latest_comparison = comparison_summary
                self.all_completed_runs.extend([baseline_result, pool_result])
                self.progress_message = "Comparison completed successfully."

        except Exception as exc:
            with self._lock:
                self.progress_message = f"Error during comparison: {exc}"
        finally:
            with self._lock:
                self.is_running = False
                self.current_engine = None
                self.current_task_type = None

    def reset_results(self) -> Tuple[bool, str]:
        """Safely clears history only when no run is active."""
        with self._lock:
            if self.is_running:
                return False, "Cannot reset results while a benchmark is currently active."
            self.latest_single_result = None
            self.latest_comparison = None
            self.all_completed_runs.clear()
            self.current_metrics = None
            self.progress_message = "Results reset successfully."
            return True, "Results reset successfully."

    def export_data(self) -> Dict[str, Any]:
        """Constructs a full export object with schema version and timestamps."""
        with self._lock:
            return {
                "schema_version": "1.0.0",
                "project": "Thread Management for High-Performance Web Servers",
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "timestamp_epoch": time.time(),
                "latest_comparison": self.latest_comparison,
                "latest_single_result": self.latest_single_result,
                "all_completed_runs": list(self.all_completed_runs)
            }
