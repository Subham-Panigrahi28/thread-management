"""
metrics.py - Thread-safe metrics collection and statistical calculations.

Operating Systems Reference:
In multi-threaded server architectures, metrics counters (e.g., requests attempted,
accepted, completed, rejected) are shared mutable state. Thread-safe updates via locks
are essential to avoid race conditions and lost updates without holding locks during
task execution or I/O waits.
"""

from __future__ import annotations
import math
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def calculate_p95(latencies: List[float]) -> Optional[float]:
    """
    Computes the 95th percentile latency using the nearest-rank method.
    Index formula: ceil(0.95 * n) - 1, clamped to [0, n - 1].
    Returns None if latencies list is empty.
    """
    if not latencies:
        return None
    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)
    rank_index = math.ceil(0.95 * n) - 1
    rank_index = max(0, min(rank_index, n - 1))
    return round(sorted_latencies[rank_index], 2)


def calculate_average(latencies: List[float]) -> Optional[float]:
    """Computes arithmetic mean of latencies. Returns None if empty."""
    if not latencies:
        return None
    return round(sum(latencies) / len(latencies), 2)


def get_system_resource_snapshot() -> Dict[str, Any]:
    """
    Optionally samples CPU and Memory utilization if psutil is available.
    If unavailable or fails, returns an explicit status rather than fabricated numbers.
    """
    if not PSUTIL_AVAILABLE:
        return {
            "available": False,
            "cpu_percent": None,
            "memory_percent": None,
            "note": "psutil not installed; resource tracking disabled"
        }
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        return {
            "available": True,
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(mem, 1),
            "note": "Sampled via local psutil"
        }
    except Exception as exc:
        return {
            "available": False,
            "cpu_percent": None,
            "memory_percent": None,
            "note": f"Error sampling resources: {exc}"
        }


class RunMetrics:
    """
    Thread-safe metrics container for an active or completed benchmark run.
    Maintains counters, latencies, max observed queue depth, and bounded recent records.
    """

    def __init__(self, run_id: str, mode: str, config: Dict[str, Any], max_history: int = 300) -> None:
        self.run_id = run_id
        self.mode = mode
        self.config = config
        self.max_history = max_history

        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        self._lock = threading.Lock()
        self.attempted: int = 0
        self.accepted: int = 0
        self.successful: int = 0
        self.rejected: int = 0
        self.failed: int = 0
        self.max_observed_queue_depth: int = 0
        self.max_active_workers: int = 0

        self.successful_latencies_ms: List[float] = []
        self.recent_records: List[Dict[str, Any]] = []

    def start(self) -> None:
        with self._lock:
            self.start_time = time.perf_counter()

    def record_attempt(self) -> None:
        with self._lock:
            self.attempted += 1

    def record_accepted(self) -> None:
        with self._lock:
            self.accepted += 1

    def record_rejection(self, request_id: str, reason: str = "Queue full") -> None:
        with self._lock:
            self.rejected += 1
            record = {
                "request_id": request_id,
                "status": "REJECTED",
                "latency_ms": 0.0,
                "worker": "dispatcher",
                "reason": reason,
                "timestamp": round(time.time(), 3)
            }
            self._append_record(record)

    def update_queue_depth(self, current_depth: int) -> None:
        with self._lock:
            if current_depth > self.max_observed_queue_depth:
                self.max_observed_queue_depth = current_depth

    def update_active_workers(self, current_active: int) -> None:
        with self._lock:
            if current_active > self.max_active_workers:
                self.max_active_workers = current_active

    def record_task_completion(self, request_id: str, success: bool, latency_ms: float,
                               worker_name: str, error_msg: Optional[str] = None) -> None:
        with self._lock:
            if success:
                self.successful += 1
                self.successful_latencies_ms.append(latency_ms)
                status = "SUCCESS"
            else:
                self.failed += 1
                status = "FAILED"

            record = {
                "request_id": request_id,
                "status": status,
                "latency_ms": round(latency_ms, 2),
                "worker": worker_name,
                "error": error_msg,
                "timestamp": round(time.time(), 3)
            }
            self._append_record(record)

    def _append_record(self, record: Dict[str, Any]) -> None:
        # Assumes caller holds self._lock
        if len(self.recent_records) >= self.max_history:
            self.recent_records.pop(0)
        self.recent_records.append(record)

    def stop(self) -> None:
        with self._lock:
            if self.end_time is None:
                self.end_time = time.perf_counter()

    def snapshot(self) -> Dict[str, Any]:
        """Returns a consistent read-only summary snapshot of the metrics."""
        with self._lock:
            now = time.perf_counter()
            start = self.start_time or now
            end = self.end_time or now
            duration = max(0.0001, end - start)

            latencies = list(self.successful_latencies_ms)
            avg_latency = calculate_average(latencies)
            p95_latency = calculate_p95(latencies)
            min_latency = round(min(latencies), 2) if latencies else None
            max_latency = round(max(latencies), 2) if latencies else None

            # Throughput = successful completions / wall-clock duration
            throughput = round(self.successful / duration, 2)

            return {
                "run_id": self.run_id,
                "mode": self.mode,
                "config": dict(self.config),
                "duration_seconds": round(duration, 3),
                "attempted": self.attempted,
                "accepted": self.accepted,
                "successful": self.successful,
                "rejected": self.rejected,
                "failed": self.failed,
                "throughput_req_per_sec": throughput,
                "avg_latency_ms": avg_latency,
                "p95_latency_ms": p95_latency,
                "min_latency_ms": min_latency,
                "max_latency_ms": max_latency,
                "max_observed_queue_depth": self.max_observed_queue_depth,
                "max_active_workers": self.max_active_workers,
                "is_completed": self.end_time is not None,
                "recent_records": list(reversed(self.recent_records[-50:]))  # newest first
            }
