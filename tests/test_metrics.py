"""
test_metrics.py - Unit tests for metrics calculation and thread-safe accumulation.
Covers Section 8 minimum tests:
1. Empty metrics and zero-success cases.
2. Average and p95 latency calculations using known samples.
"""

import math
import unittest
from metrics import calculate_average, calculate_p95, RunMetrics


class TestMetricsCalculations(unittest.TestCase):
    def test_empty_metrics_and_zero_success(self):
        """Test 1: Empty metrics and zero-success cases return None for latencies."""
        self.assertIsNone(calculate_average([]))
        self.assertIsNone(calculate_p95([]))

        metrics = RunMetrics(run_id="test-zero", mode="baseline", config={})
        metrics.start()
        metrics.record_attempt()
        metrics.record_rejection("req-1", reason="Queue full")
        metrics.stop()

        snap = metrics.snapshot()
        self.assertEqual(snap["attempted"], 1)
        self.assertEqual(snap["accepted"], 0)
        self.assertEqual(snap["successful"], 0)
        self.assertEqual(snap["rejected"], 1)
        self.assertEqual(snap["throughput_req_per_sec"], 0.0)
        self.assertIsNone(snap["avg_latency_ms"])
        self.assertIsNone(snap["p95_latency_ms"])

    def test_p95_and_average_known_samples(self):
        """Test 2: Known samples for average and nearest-rank p95."""
        # 100 samples from 1 to 100
        samples = list(range(1, 101))
        # Avg = (1 + 100) / 2 = 50.5
        avg = calculate_average(samples)
        self.assertEqual(avg, 50.5)

        # Nearest-rank p95: n = 100, index = ceil(0.95 * 100) - 1 = 95 - 1 = 94 -> 95
        p95 = calculate_p95(samples)
        self.assertEqual(p95, 95.0)

        # Small sample: [10.0, 20.0, 30.0]
        # n = 3, index = ceil(0.95 * 3) - 1 = ceil(2.85) - 1 = 3 - 1 = 2 -> 30.0
        small_samples = [10.0, 20.0, 30.0]
        self.assertEqual(calculate_average(small_samples), 20.0)
        self.assertEqual(calculate_p95(small_samples), 30.0)

        # Single element sample
        self.assertEqual(calculate_p95([42.0]), 42.0)
        self.assertEqual(calculate_average([42.0]), 42.0)

    def test_metrics_bounded_history(self):
        """Verifies recent record history stays bounded at configured limit."""
        metrics = RunMetrics(run_id="test-hist", mode="pool", config={}, max_history=10)
        metrics.start()
        for i in range(25):
            metrics.record_task_completion(
                request_id=f"req-{i}",
                success=True,
                latency_ms=5.0,
                worker_name="Worker-1"
            )
        metrics.stop()

        snap = metrics.snapshot()
        self.assertEqual(snap["successful"], 25)
        # Bounded history should be <= 10
        self.assertLessEqual(len(metrics.recent_records), 10)


if __name__ == "__main__":
    unittest.main()
