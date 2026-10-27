"""
test_benchmark.py - Integration and API tests for benchmark coordination.
Covers Section 8 minimum tests:
7. Reset is blocked/rejected while benchmark is active.
8. API rejects malformed JSON and invalid settings.
9. Comparison returns baseline and pool results.
10. Export parses as valid JSON.
12. A small end-to-end benchmark completes successfully.
"""

import json
import threading
import time
import unittest
from app import validate_settings
from benchmark import BenchmarkManager


class TestBenchmarkManagerAndAPI(unittest.TestCase):
    def test_api_validation(self):
        """Test 8: API rejects invalid settings and enforces project limits."""
        # Valid settings
        valid, settings, err = validate_settings({
            "mode": "bounded_pool",
            "worker_count": 8,
            "queue_capacity": 100,
            "request_count": 50,
            "producer_concurrency": 5,
            "simulated_io_ms": 10.0
        })
        self.assertTrue(valid)
        self.assertEqual(settings["worker_count"], 8)

        # Invalid worker count (> 32)
        valid, _, err = validate_settings({"worker_count": 64})
        self.assertFalse(valid)
        self.assertIn("Worker count", err)

        # Invalid queue capacity (> 2000)
        valid, _, err = validate_settings({"queue_capacity": 5000})
        self.assertFalse(valid)
        self.assertIn("Queue capacity", err)

        # Invalid mode
        valid, _, err = validate_settings({"mode": "invalid_mode"})
        self.assertFalse(valid)
        self.assertIn("Invalid mode", err)

        # Invalid request count (< 10)
        valid, _, err = validate_settings({"request_count": 2})
        self.assertFalse(valid)
        self.assertIn("Request count", err)

        # Invalid producer concurrency (> 100)
        valid, _, err = validate_settings({"producer_concurrency": 200})
        self.assertFalse(valid)
        self.assertIn("Producer concurrency", err)

    def test_reset_blocked_while_benchmark_active(self):
        """Test 7: Reset is blocked and returns error while benchmark is active."""
        mgr = BenchmarkManager()
        # Mark manager as running
        mgr.is_running = True

        ok, msg = mgr.reset_results()
        self.assertFalse(ok)
        self.assertIn("Cannot reset", msg)

        # When stopped, reset succeeds
        mgr.is_running = False
        ok, msg = mgr.reset_results()
        self.assertTrue(ok)

    def test_export_parses_as_valid_json(self):
        """Test 10: Export returns well-structured, valid JSON data."""
        mgr = BenchmarkManager()
        export_dict = mgr.export_data()

        # Must serialize cleanly to valid JSON string and parse back
        json_str = json.dumps(export_dict)
        parsed = json.loads(json_str)

        self.assertEqual(parsed["schema_version"], "1.0.0")
        self.assertIn("timestamp_epoch", parsed)
        self.assertIn("all_completed_runs", parsed)

    def test_small_end_to_end_single_benchmark(self):
        """Test 12: A small end-to-end benchmark completes successfully."""
        mgr = BenchmarkManager()
        started, msg = mgr.start_single_benchmark(
            mode="bounded_pool",
            request_count=20,
            producer_concurrency=4,
            worker_count=4,
            queue_capacity=50,
            simulated_io_ms=0.0
        )
        self.assertTrue(started)

        # Wait for completion (fast 0ms run)
        deadline = time.time() + 5.0
        while mgr.is_running and time.time() < deadline:
            time.sleep(0.05)

        self.assertFalse(mgr.is_running, "Benchmark did not complete in time")
        status = mgr.get_status()
        self.assertFalse(status["is_running"])
        self.assertIsNotNone(mgr.latest_single_result)
        self.assertEqual(mgr.latest_single_result["successful"], 20)
        self.assertGreater(mgr.latest_single_result["throughput_req_per_sec"], 0)

    def test_comparison_returns_baseline_and_pool_results(self):
        """Test 9: Comparison returns both baseline and pool results."""
        mgr = BenchmarkManager()
        started, msg = mgr.start_comparison(
            request_count=20,
            producer_concurrency=4,
            worker_count=4,
            queue_capacity=50,
            simulated_io_ms=1.0
        )
        self.assertTrue(started)

        # Wait for completion
        deadline = time.time() + 10.0
        while mgr.is_running and time.time() < deadline:
            time.sleep(0.1)

        self.assertFalse(mgr.is_running, "Comparison did not complete in time")
        self.assertIsNotNone(mgr.latest_comparison)
        comp = mgr.latest_comparison

        self.assertIn("baseline", comp)
        self.assertIn("bounded_pool", comp)
        self.assertEqual(comp["baseline"]["successful"], 20)
        self.assertEqual(comp["bounded_pool"]["successful"], 20)
        self.assertIsNotNone(comp["duration_speedup"])
        self.assertIsNotNone(comp["throughput_ratio"])


if __name__ == "__main__":
    unittest.main()
