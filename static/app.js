/**
 * app.js - Frontend application controller for Thread Management demonstration.
 * Zero external dependencies. Uses standard fetch API and SVG DOM generation.
 */

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const selectMode = document.getElementById("selectMode");
  const inputWorkers = document.getElementById("inputWorkers");
  const lblWorkers = document.getElementById("lblWorkers");
  const inputQueueCap = document.getElementById("inputQueueCap");
  const lblQueueCap = document.getElementById("lblQueueCap");
  const inputReqCount = document.getElementById("inputReqCount");
  const lblReqCount = document.getElementById("lblReqCount");
  const inputProducerConc = document.getElementById("inputProducerConc");
  const lblProducerConc = document.getElementById("lblProducerConc");
  const selectWorkload = document.getElementById("selectWorkload");

  const btnRunSingle = document.getElementById("btnRunSingle");
  const btnRunCompare = document.getElementById("btnRunCompare");
  const btnReset = document.getElementById("btnReset");
  const btnExport = document.getElementById("btnExport");

  // Status Bar
  const statusBar = document.getElementById("statusBar");
  const statusTitle = document.getElementById("statusTitle");
  const statusSub = document.getElementById("statusSub");
  const meterQueue = document.getElementById("meterQueue");
  const meterWorkers = document.getElementById("meterWorkers");
  const activeRunBadge = document.getElementById("activeRunBadge");

  // Metric Cards
  const valThroughput = document.getElementById("valThroughput");
  const valAvgLatency = document.getElementById("valAvgLatency");
  const valP95Latency = document.getElementById("valP95Latency");
  const valDuration = document.getElementById("valDuration");
  const valSuccessful = document.getElementById("valSuccessful");
  const valAttempted = document.getElementById("valAttempted");
  const valAccepted = document.getElementById("valAccepted");
  const valRejected = document.getElementById("valRejected");
  const valFailed = document.getElementById("valFailed");
  const valMaxQueue = document.getElementById("valMaxQueue");

  // Comparison section
  const compareEmpty = document.getElementById("compareEmpty");
  const compareContent = document.getElementById("compareContent");
  const compTimestamp = document.getElementById("compTimestamp");
  const visualChartContainer = document.getElementById("visualChartContainer");
  const tblPoolWorkers = document.getElementById("tblPoolWorkers");

  // Table Cells
  const tblBaseThroughput = document.getElementById("tblBaseThroughput");
  const tblPoolThroughput = document.getElementById("tblPoolThroughput");
  const tblDiffThroughput = document.getElementById("tblDiffThroughput");

  const tblBaseDuration = document.getElementById("tblBaseDuration");
  const tblPoolDuration = document.getElementById("tblPoolDuration");
  const tblDiffDuration = document.getElementById("tblDiffDuration");

  const tblBaseAvgLat = document.getElementById("tblBaseAvgLat");
  const tblPoolAvgLat = document.getElementById("tblPoolAvgLat");
  const tblDiffAvgLat = document.getElementById("tblDiffAvgLat");

  const tblBaseP95 = document.getElementById("tblBaseP95");
  const tblPoolP95 = document.getElementById("tblPoolP95");
  const tblDiffP95 = document.getElementById("tblDiffP95");

  const tblBaseSuccess = document.getElementById("tblBaseSuccess");
  const tblPoolSuccess = document.getElementById("tblPoolSuccess");

  const tblBaseRejections = document.getElementById("tblBaseRejections");
  const tblPoolRejections = document.getElementById("tblPoolRejections");
  const tblDiffRejections = document.getElementById("tblDiffRejections");

  const tblBaseMaxQueue = document.getElementById("tblBaseMaxQueue");
  const tblPoolMaxQueue = document.getElementById("tblPoolMaxQueue");
  const tblDiffMaxQueue = document.getElementById("tblDiffMaxQueue");

  // Log & Telemetry
  const logTableBody = document.getElementById("logTableBody");
  const telemetryStatus = document.getElementById("telemetryStatus");

  let pollingInterval = null;
  let isCurrentlyPolling = false;

  // Slider synchronization
  inputWorkers.addEventListener("input", (e) => { lblWorkers.textContent = e.target.value; });
  inputQueueCap.addEventListener("input", (e) => { lblQueueCap.textContent = e.target.value; });
  inputReqCount.addEventListener("input", (e) => { lblReqCount.textContent = e.target.value; });
  inputProducerConc.addEventListener("input", (e) => { lblProducerConc.textContent = e.target.value; });

  function getFormConfig() {
    return {
      mode: selectMode.value,
      worker_count: parseInt(inputWorkers.value, 10),
      queue_capacity: parseInt(inputQueueCap.value, 10),
      request_count: parseInt(inputReqCount.value, 10),
      producer_concurrency: parseInt(inputProducerConc.value, 10),
      simulated_io_ms: parseFloat(selectWorkload.value)
    };
  }

  function setActionButtonsDisabled(disabled) {
    btnRunSingle.disabled = disabled;
    btnRunCompare.disabled = disabled;
    btnReset.disabled = disabled;
    selectMode.disabled = disabled;
  }

  // --- API Calls ---

  async function startBenchmark(endpoint, payload) {
    try {
      setActionButtonsDisabled(true);
      statusBar.className = "status-bar status-running";
      statusTitle.textContent = "Status: Initializing Run...";
      statusSub.textContent = "Dispatching request to server engine...";

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to start benchmark.");
      }

      startPolling();
    } catch (err) {
      alert("Error: " + err.message);
      setActionButtonsDisabled(false);
      statusBar.className = "status-bar status-idle";
      statusTitle.textContent = "Status: Idle";
      statusSub.textContent = err.message;
    }
  }

  btnRunSingle.addEventListener("click", () => {
    const config = getFormConfig();
    startBenchmark("/api/benchmark", config);
  });

  btnRunCompare.addEventListener("click", () => {
    const config = getFormConfig();
    startBenchmark("/api/compare", config);
  });

  btnReset.addEventListener("click", async () => {
    if (!confirm("Are you sure you want to reset all current metrics and history?")) {
      return;
    }
    try {
      const res = await fetch("/api/reset", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);

      // Reset UI to clean state
      resetUIDisplay();
      statusTitle.textContent = "Status: Ready";
      statusSub.textContent = "Results reset successfully.";
    } catch (err) {
      alert("Error resetting results: " + err.message);
    }
  });

  btnExport.addEventListener("click", () => {
    window.location.href = "/api/export";
  });

  // --- Polling and UI Updates ---

  function startPolling() {
    if (isCurrentlyPolling) return;
    isCurrentlyPolling = true;

    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(pollStatus, 600);
    pollStatus();
  }

  function stopPolling() {
    if (pollingInterval) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
    isCurrentlyPolling = false;
    setActionButtonsDisabled(false);
  }

  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const status = await res.json();

      updateTelemetry(status.system_resources);

      if (status.is_running) {
        statusBar.className = "status-bar status-running";
        statusTitle.textContent = `Status: Running (${status.engine_name || "Task"})`;
        statusSub.textContent = status.progress_message;
        meterQueue.textContent = status.queue_depth;
        meterWorkers.textContent = status.active_workers;

        if (status.active_metrics) {
          renderMetricsCard(status.active_metrics);
          renderRecentLog(status.active_metrics.recent_records);
        }
      } else {
        // Run has finished
        stopPolling();
        statusBar.className = "status-bar status-idle";
        statusTitle.textContent = "Status: Completed";
        statusSub.textContent = status.progress_message;
        meterQueue.textContent = "0";
        meterWorkers.textContent = "0";

        // Fetch full results
        await fetchFullResults();
      }
    } catch (err) {
      console.error("Polling error:", err);
    }
  }

  async function fetchFullResults() {
    try {
      const res = await fetch("/api/results");
      if (!res.ok) return;
      const data = await res.json();

      if (data.latest_comparison) {
        renderComparison(data.latest_comparison);
        renderMetricsCard(data.latest_comparison.bounded_pool);
        renderRecentLog(data.latest_comparison.bounded_pool.recent_records);
      } else if (data.latest_single_result) {
        renderMetricsCard(data.latest_single_result);
        renderRecentLog(data.latest_single_result.recent_records);
      }
    } catch (err) {
      console.error("Error fetching results:", err);
    }
  }

  function renderMetricsCard(m) {
    if (!m) return;
    activeRunBadge.className = "mode-badge badge-active";
    activeRunBadge.textContent = m.mode === "baseline" ? "Sequential Baseline" : `Bounded Pool (${m.config.worker_count}w)`;

    valThroughput.textContent = m.throughput_req_per_sec !== null ? m.throughput_req_per_sec.toFixed(1) : "—";
    valAvgLatency.textContent = m.avg_latency_ms !== null ? m.avg_latency_ms.toFixed(1) : "—";
    valP95Latency.textContent = m.p95_latency_ms !== null ? m.p95_latency_ms.toFixed(1) : "—";
    valDuration.textContent = m.duration_seconds !== null ? m.duration_seconds.toFixed(2) + "s" : "—";

    valSuccessful.textContent = m.successful;
    valAttempted.textContent = m.attempted;
    valAccepted.textContent = m.accepted;
    valRejected.textContent = m.rejected;
    valFailed.textContent = m.failed;
    valMaxQueue.textContent = m.max_observed_queue_depth;
  }

  function renderComparison(comp) {
    if (!comp) return;
    compareEmpty.style.display = "none";
    compareContent.style.display = "block";

    const base = comp.baseline;
    const pool = comp.bounded_pool;
    const s = comp.settings;

    compTimestamp.textContent = `Completed at ${new Date(comp.timestamp * 1000).toLocaleTimeString()} (${s.request_count} reqs, ${s.simulated_io_ms}ms I/O)`;
    tblPoolWorkers.textContent = s.worker_count;

    // Baseline
    tblBaseThroughput.textContent = `${base.throughput_req_per_sec} req/s`;
    tblBaseDuration.textContent = `${base.duration_seconds}s`;
    tblBaseAvgLat.textContent = base.avg_latency_ms !== null ? `${base.avg_latency_ms} ms` : "—";
    tblBaseP95.textContent = base.p95_latency_ms !== null ? `${base.p95_latency_ms} ms` : "—";
    tblBaseSuccess.textContent = `${base.successful} / ${base.attempted}`;
    tblBaseRejections.textContent = base.rejected;
    tblBaseMaxQueue.textContent = base.max_observed_queue_depth;

    // Pool
    tblPoolThroughput.textContent = `${pool.throughput_req_per_sec} req/s`;
    tblPoolDuration.textContent = `${pool.duration_seconds}s`;
    tblPoolAvgLat.textContent = pool.avg_latency_ms !== null ? `${pool.avg_latency_ms} ms` : "—";
    tblPoolP95.textContent = pool.p95_latency_ms !== null ? `${pool.p95_latency_ms} ms` : "—";
    tblPoolSuccess.textContent = `${pool.successful} / ${pool.attempted}`;
    tblPoolRejections.textContent = pool.rejected;
    tblPoolMaxQueue.textContent = pool.max_observed_queue_depth;

    // Diff / Speedup
    if (comp.duration_speedup) {
      tblDiffDuration.textContent = `${comp.duration_speedup}x Faster`;
    } else {
      tblDiffDuration.textContent = "—";
    }

    if (comp.throughput_ratio) {
      tblDiffThroughput.textContent = `${comp.throughput_ratio}x Throughput`;
    } else {
      tblDiffThroughput.textContent = "—";
    }

    if (base.avg_latency_ms && pool.avg_latency_ms) {
      const latDiff = (base.avg_latency_ms - pool.avg_latency_ms).toFixed(1);
      tblDiffAvgLat.textContent = latDiff >= 0 ? `-${latDiff} ms (Improved)` : `+${Math.abs(latDiff)} ms`;
    } else {
      tblDiffAvgLat.textContent = "—";
    }

    if (base.p95_latency_ms && pool.p95_latency_ms) {
      const p95Diff = (base.p95_latency_ms - pool.p95_latency_ms).toFixed(1);
      tblDiffP95.textContent = p95Diff >= 0 ? `-${p95Diff} ms` : `+${Math.abs(p95Diff)} ms`;
    } else {
      tblDiffP95.textContent = "—";
    }

    tblDiffRejections.textContent = pool.rejected === base.rejected ? "Identical" : `${pool.rejected - base.rejected} net`;
    tblDiffMaxQueue.textContent = `Baseline: ${base.max_observed_queue_depth} | Pool: ${pool.max_observed_queue_depth}`;

    // Render SVG visual chart
    renderVisualChart(base, pool);
  }

  function renderVisualChart(base, pool) {
    const maxThroughput = Math.max(1, base.throughput_req_per_sec, pool.throughput_req_per_sec);
    const maxDuration = Math.max(0.1, base.duration_seconds, pool.duration_seconds);

    const baseTWidth = Math.min(380, Math.round((base.throughput_req_per_sec / maxThroughput) * 380));
    const poolTWidth = Math.min(380, Math.round((pool.throughput_req_per_sec / maxThroughput) * 380));

    const baseDWidth = Math.min(380, Math.round((base.duration_seconds / maxDuration) * 380));
    const poolDWidth = Math.min(380, Math.round((pool.duration_seconds / maxDuration) * 380));

    const svgHtml = `
      <svg class="svg-chart" viewBox="0 0 650 160" preserveAspectRatio="xMidYMid meet">
        <!-- Section 1: Throughput -->
        <text x="10" y="22" class="chart-label" font-weight="700">Throughput (higher is better)</text>
        
        <text x="10" y="44" class="chart-label">Baseline (1w):</text>
        <rect x="130" y="32" width="${Math.max(4, baseTWidth)}" height="16" rx="3" class="chart-bar-baseline"></rect>
        <text x="${140 + Math.max(4, baseTWidth)}" y="44" class="chart-val">${base.throughput_req_per_sec} req/s</text>

        <text x="10" y="68" class="chart-label">Bounded Pool:</text>
        <rect x="130" y="56" width="${Math.max(4, poolTWidth)}" height="16" rx="3" class="chart-bar-pool"></rect>
        <text x="${140 + Math.max(4, poolTWidth)}" y="68" class="chart-val">${pool.throughput_req_per_sec} req/s</text>

        <!-- Divider -->
        <line x1="10" y1="86" x2="630" y2="86" stroke="#334155" stroke-dasharray="3,3" />

        <!-- Section 2: Wall-Clock Duration -->
        <text x="10" y="106" class="chart-label" font-weight="700">Duration (lower is better)</text>

        <text x="10" y="128" class="chart-label">Baseline (1w):</text>
        <rect x="130" y="116" width="${Math.max(4, baseDWidth)}" height="16" rx="3" class="chart-bar-baseline"></rect>
        <text x="${140 + Math.max(4, baseDWidth)}" y="128" class="chart-val">${base.duration_seconds}s</text>

        <text x="10" y="152" class="chart-label">Bounded Pool:</text>
        <rect x="130" y="140" width="${Math.max(4, poolDWidth)}" height="16" rx="3" class="chart-bar-pool"></rect>
        <text x="${140 + Math.max(4, poolDWidth)}" y="152" class="chart-val">${pool.duration_seconds}s</text>
      </svg>
    `;

    visualChartContainer.innerHTML = svgHtml;
  }

  function renderRecentLog(records) {
    if (!records || records.length === 0) {
      logTableBody.innerHTML = `<tr><td colspan="6" class="text-center empty-cell">No request events logged yet.</td></tr>`;
      return;
    }

    const rows = records.slice(0, 30).map(r => {
      let pillClass = "pill-success";
      if (r.status === "REJECTED") pillClass = "pill-rejected";
      if (r.status === "FAILED") pillClass = "pill-failed";

      const timeStr = r.timestamp ? new Date(r.timestamp * 1000).toLocaleTimeString() : "—";
      const latencyStr = r.latency_ms !== undefined ? `${r.latency_ms} ms` : "—";
      const noteStr = r.reason || r.error || "Completed OK";

      return `
        <tr>
          <td>${timeStr}</td>
          <td><code>${r.request_id}</code></td>
          <td>${r.worker || "—"}</td>
          <td><span class="status-pill ${pillClass}">${r.status}</span></td>
          <td>${latencyStr}</td>
          <td>${noteStr}</td>
        </tr>
      `;
    }).join("");

    logTableBody.innerHTML = rows;
  }

  function updateTelemetry(resources) {
    if (!resources || !resources.available) {
      telemetryStatus.textContent = "Host CPU/RAM telemetry: Not available on this setup (honest reporting).";
      return;
    }
    telemetryStatus.textContent = `CPU: ${resources.cpu_percent}% | RAM: ${resources.memory_percent}% (${resources.note})`;
  }

  function resetUIDisplay() {
    activeRunBadge.className = "mode-badge badge-neutral";
    activeRunBadge.textContent = "No Run Selected";

    valThroughput.textContent = "—";
    valAvgLatency.textContent = "—";
    valP95Latency.textContent = "—";
    valDuration.textContent = "—";
    valSuccessful.textContent = "0";
    valAttempted.textContent = "0";
    valAccepted.textContent = "0";
    valRejected.textContent = "0";
    valFailed.textContent = "0";
    valMaxQueue.textContent = "0";

    compareEmpty.style.display = "block";
    compareContent.style.display = "none";
    visualChartContainer.innerHTML = "";

    logTableBody.innerHTML = `<tr><td colspan="6" class="text-center empty-cell">Results cleared. Ready for next evaluation.</td></tr>`;
  }

  // Initial check on load
  pollStatus();
});
