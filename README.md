# Thread Management for High-Performance Web Servers
## Operating Systems Laboratory Demonstration & Evaluation

> **Course:** Operating Systems  
> **Topic:** Multi-threading, Synchronization, Producer-Consumer Architectures, and Bounded Worker Pools  
> **Implementation:** Pure Python 3.10+ (Standard Library) + Plain HTML/CSS/JavaScript (Zero CDN / Offline)

---

## 1. Project Overview & Objectives

In web server architectures, handling incoming client traffic efficiently requires balancing responsiveness, system throughput, and resource utilization. Spawning an unconstrained number of operating system threads per request leads to thread-exhaustion, severe context-switching overhead, and kernel thrashing. 

This project implements and evaluates two distinct concurrency architectures:
1. **Sequential Baseline (1 Worker):** Incoming requests are placed in a FIFO queue and processed sequentially by a single worker thread.
2. **Bounded Thread Pool (Multi-Worker):** A pre-spawned fixed pool of reusable worker threads concurrently consumes incoming requests from a bounded thread-safe FIFO queue (`queue.Queue(maxsize=capacity)`).

The application provides an interactive engineering dashboard to configure workloads, run benchmarks, execute side-by-side fair comparisons, visualize latency percentiles (p95) and throughput, inspect recent request streams, and export raw evaluation data.

---

## 2. Core Operating Systems Concepts Demonstrated

### 2.1 Producer-Consumer Pattern & Bounded FIFO Queue
- **Producers:** Concurrent client connections modeled using a fixed producer pool (`concurrent.futures.ThreadPoolExecutor`).
- **Bounded Buffer:** A synchronized queue (`queue.Queue(maxsize=capacity)`) that prevents unbounded memory consumption under load.
- **Back-pressure & Overload Policy:** When the queue reaches its maximum capacity, new submissions immediately trigger back-pressure (`queue.Full`) and are counted as **Rejections** rather than silently dropping or crashing the server.

### 2.2 Thread Pooling & Worker Reuse
- Instead of the expensive overhead of creating and destroying kernel/user threads on every request, worker threads are spawned once at server startup and remain alive, continuously waiting on `queue.get()`.
- Thread termination uses sentinel poison pills (`None` / `_SENTINEL`) and `join()` to ensure graceful shutdown without orphaned threads.

### 2.3 Synchronization & Race Condition Prevention
- Counters (attempted, accepted, completed, rejected) and the recent request history buffer are protected by non-nested mutex locks (`threading.Lock`).
- **Critical Section Isolation:** Mutex locks are **never held** while sleeping or executing simulated I/O tasks (`time.sleep()`), allowing true concurrent overlap.

### 2.4 Latency Percentiles vs Arithmetic Mean
- Average latency can obscure tail latency issues caused by queue queuing delays.
- The 95th Percentile ($p_{95}$) is calculated using the **nearest-rank method**:
  $$\text{Index} = \max\left(0, \min\left(\lceil 0.95 \times n \rceil - 1, n - 1\right)\right)$$
  ensuring an accurate representation of the worst-case experience for 95% of requests.

---

## 3. Project Architecture & File Structure

```text
thread-management-web-server/
├── app.py                      # Local HTTP server and REST API (bound to 127.0.0.1)
├── server_engine.py            # Baseline and Bounded Thread Pool server implementations
├── benchmark.py                # Asynchronous benchmark runner & producer load generator
├── metrics.py                  # Thread-safe metrics collection and p95 nearest-rank calculations
├── benchmark_run_evidence.json # Verified end-to-end benchmark comparison export
├── static/
│   ├── index.html              # Responsive engineering dashboard
│   ├── styles.css              # Dark navy / charcoal styling (no CDN dependencies)
│   └── app.js                  # Frontend controller & pure SVG comparison chart generator
├── tests/
│   ├── test_metrics.py         # Unit tests for p95, average, and zero-success scenarios
│   ├── test_server_engine.py   # Concurrency, queue overflow, and worker failure tests
│   └── test_benchmark.py       # API validation, comparison flow, and JSON export tests
├── requirements.txt            # Optional psutil dependency (core uses Python standard library)
├── .gitignore                  # Git ignore rules
└── README.md                   # Complete viva defense and run guide
```

---

## 4. Setup & Launch Instructions

### Prerequisites
- Python 3.10, 3.11, 3.12, or newer.
- No external packages required for core server or tests (all standard library).
- (Optional) `pip install psutil` to display live host CPU and memory telemetry.

### Windows (PowerShell)
```powershell
# 1. Verify Python installation
python --version

# 2. Run automated test suite
python -m unittest discover -s tests -v

# 3. Start the application server
python app.py
```

### macOS / Linux (Terminal)
```bash
# 1. Verify Python installation
python3 --version

# 2. Run automated test suite
python3 -m unittest discover -s tests -v

# 3. Start the application server
python3 app.py
```

Open your browser to:
**`http://127.0.0.1:8080/`**

> **Note on Port Conflict:** If port 8080 is already in use by another service on your machine, specify an alternate port:
> ```bash
> python app.py --port 8085
> ```
> And navigate to `http://127.0.0.1:8085/`.

---

## 5. Metric Definitions

| Metric | Definition & Computation |
| :--- | :--- |
| **Attempted Requests** | Total number of client requests dispatched toward the server queue. |
| **Accepted Requests** | Requests successfully placed into the server's FIFO queue. |
| **Completed Requests** | Requests fully processed by worker threads (successes + failures). |
| **Rejected Requests** | Requests rejected immediately due to queue capacity overflow (`queue.Full`). |
| **Wall-Clock Duration** | Total elapsed time ($t_{\text{end}} - t_{\text{start}}$) measured with `time.perf_counter()`. |
| **Throughput** | $\text{Successful Completions} \div \text{Wall-Clock Duration (seconds)}$. |
| **Average Latency** | Arithmetic mean of individual execution latencies for successful tasks. |
| **p95 Latency** | 95th percentile latency using the nearest-rank index of sorted latencies. |
| **Max Queue Depth** | Maximum observed instantaneous task backlog in `queue.Queue`. |

---

## 6. How to Demonstrate in a 5–8 Minute Viva

### Step 1: Explain the Architecture (1.5 minutes)
- Point to the **How It Works** section on the dashboard:
  - Mention the **Producer-Consumer pattern**: incoming client requests are placed into a bounded queue.
  - Explain that the **Sequential Baseline** uses 1 single worker thread, while the **Bounded Thread Pool** uses a configurable fixed pool (e.g., 8 workers).

### Step 2: Run Fair Comparison (2 minutes)
- Keep default settings:
  - Requests: **100 or 200**
  - Concurrency: **10**
  - Worker Threads: **8**
  - Queue Capacity: **100**
  - Simulated Workload: **Simulated I/O Wait (20–50 ms)**
- Click **Run Fair Comparison (Baseline vs Pool)**.
- Note how the status bar shows **Phase 1 (Baseline)** followed by **Phase 2 (Pool)**.
- Observe how the browser UI remains completely responsive and updates in real time.

### Step 3: Analyze the Results Table & SVG Chart (2 minutes)
- Point out the **Visual Throughput & Duration Comparison**:
  - The Bounded Thread Pool achieves a **~7.5x speedup** in wall-clock completion time and a matching throughput increase over the sequential baseline.
  - Average latency for individual tasks remains ~20 ms, but the server handles 8 tasks in parallel instead of 1 by 1.

### Step 4: Demonstrate Overload & Rejection Policy (1.5 minutes)
- Set **Bounded Queue Capacity** to a very small value (e.g., **5**).
- Set **Total Requests** to **100** and click **Run Single Benchmark**.
- Show the examiner the **Queue Overload / Failures** metric: excess requests beyond capacity are rejected immediately (`REJECTED`) without hanging or crashing the server.
- Click **Export JSON** to show how all data can be downloaded for reporting.

---

## 7. Viva Questions & Model Answers

### Q1: Why do we use a thread pool instead of creating a new thread for each request?
**Answer:** Creating an operating system thread incurs kernel stack allocation, page table manipulation, and cleanup overhead. Spawning threads per request under high load leads to thread exhaustion, heavy memory usage, and context-switching degradation. A thread pool amortizes creation costs by keeping worker threads alive to process tasks continuously.

### Q2: What happens when the request queue is bounded vs unbounded?
**Answer:** An unbounded queue allows incoming requests to accumulate indefinitely during traffic spikes, eventually exhausting process memory (Out-Of-Memory crash). A bounded queue enforces back-pressure: when the queue fills up, excess requests are rejected or deferred immediately, protecting server stability.

### Q3: How does Python's Global Interpreter Lock (GIL) affect this demonstration?
**Answer:** Standard CPython uses a GIL that allows only one thread to execute Python bytecode at a time. However, during blocking I/O operations (or `time.sleep()`, socket operations, and database calls), the GIL is released. In I/O-bound web server workloads, multi-threading yields dramatic speedups because multiple worker threads overlap their I/O waits concurrently. For purely CPU-bound tasks, multi-processing or native extensions would be required.

### Q4: Why is p95 latency more informative than average latency?
**Answer:** Average latency averages out outliers. If 95 requests finish in 10 ms and 5 requests take 5000 ms, the average appears reasonable (~260 ms), hiding the fact that 5% of users experience unacceptable slowdowns. The 95th percentile captures the tail latency ceiling.

### Q5: How did you prevent race conditions in your implementation?
**Answer:** Shared counters (attempted, completed, rejected) and the recent log list are synchronized using `threading.Lock`. Critical sections are strictly bounded: locks are acquired only for updating counters and are never held during task execution or sleeps.

---

## 8. Automated Test Suite Evidence

The test suite covers all 12 mandatory specification scenarios using Python's standard `unittest`:
```powershell
python -m unittest discover -s tests -v
```

### Verified Test Results
```text
test_api_validation (test_benchmark.TestBenchmarkManagerAndAPI.test_api_validation)
Test 8: API rejects invalid settings and enforces project limits. ... ok
test_comparison_returns_baseline_and_pool_results (test_benchmark.TestBenchmarkManagerAndAPI.test_comparison_returns_baseline_and_pool_results)
Test 9: Comparison returns both baseline and pool results. ... ok
test_export_parses_as_valid_json (test_benchmark.TestBenchmarkManagerAndAPI.test_export_parses_as_valid_json)
Test 10: Export returns well-structured, valid JSON data. ... ok
test_reset_blocked_while_benchmark_active (test_benchmark.TestBenchmarkManagerAndAPI.test_reset_blocked_while_benchmark_active)
Test 7: Reset is blocked and returns error while benchmark is active. ... ok
test_small_end_to_end_single_benchmark (test_benchmark.TestBenchmarkManagerAndAPI.test_small_end_to_end_single_benchmark)
Test 12: A small end-to-end benchmark completes successfully. ... ok
test_empty_metrics_and_zero_success (test_metrics.TestMetricsCalculations.test_empty_metrics_and_zero_success)
Test 1: Empty metrics and zero-success cases return None for latencies. ... ok
test_metrics_bounded_history (test_metrics.TestMetricsCalculations.test_metrics_bounded_history)
Verifies recent record history stays bounded at configured limit. ... ok
test_p95_and_average_known_samples (test_metrics.TestMetricsCalculations.test_p95_and_average_known_samples)
Test 2: Known samples for average and nearest-rank p95. ... ok
test_baseline_processes_tasks (test_server_engine.TestServerEngine.test_baseline_processes_tasks)
Test 3: Baseline processes tasks sequentially and records outcomes. ... ok
test_graceful_shutdown_leaves_no_worker_threads_alive (test_server_engine.TestServerEngine.test_graceful_shutdown_leaves_no_worker_threads_alive)
Test 11: Graceful shutdown cleanly terminates all worker threads. ... ok
test_one_task_exception_does_not_kill_all_workers (test_server_engine.TestServerEngine.test_one_task_exception_does_not_kill_all_workers)
Test 6: Exception in one task records as failure but workers survive. ... ok
test_pool_processes_tasks_with_multiple_workers (test_server_engine.TestServerEngine.test_pool_processes_tasks_with_multiple_workers)
Test 4: Pool processes tasks concurrently with multiple workers. ... ok
test_queue_full_rejections_without_hanging (test_server_engine.TestServerEngine.test_queue_full_rejections_without_hanging)
Test 5: Queue-full case counts rejections without deadlock or hanging. ... ok

----------------------------------------------------------------------
Ran 13 tests in 0.781s

OK
```

---

## 9. Real Measured Benchmark Evidence

An authentic end-to-end fair comparison was executed and saved to [`benchmark_run_evidence.json`](benchmark_run_evidence.json).

**Workload Configuration:**
- Requests: 100
- Client Producer Concurrency: 10
- Queue Capacity: 100
- Simulated Workload: 20 ms I/O wait per request

**Actual Results:**
| Metric | Sequential Baseline (1 Worker) | Bounded Thread Pool (8 Workers) | Observed Difference |
| :--- | :--- | :--- | :--- |
| **Wall-Clock Duration** | 2.05 s | 0.27 s | **7.59x Faster** |
| **Throughput** | 48.77 req/sec | 370.66 req/sec | **7.60x Higher Throughput** |
| **Average Task Latency** | 20.40 ms | 20.35 ms | Identical task wait (~20 ms) |
| **p95 Tail Latency** | 20.69 ms | 20.80 ms | Bounded within single-task ceiling |
| **Successful / Attempted** | 100 / 100 | 100 / 100 | Complete execution without loss |
| **Queue Rejections** | 0 | 0 | Sufficient queue capacity |

---

## 10. Honest Limitations & Notes
- **Local Prototype:** This application is built as an educational demonstration of OS concurrency primitives and is not a distributed production web server.
- **Simulated I/O:** `time.sleep()` is used to simulate blocking socket or database wait times. The GIL is released during `sleep()`, providing representative behavior for I/O-bound web servers.
- **Headless Screenshot Capture:** On Windows headless environments without an active user desktop session, native browser screenshot rendering may fail to capture. To take a screenshot for your viva report: launch `python app.py`, open `http://127.0.0.1:8080/`, click **Run Fair Comparison**, and take a screenshot directly with `Win + Shift + S`.
