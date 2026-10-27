"""
app.py - HTTP Server and REST API for Thread Management OS Project.

Operating Systems Reference:
Provides a browser interface and API endpoints bound strictly to 127.0.0.1.
All concurrent benchmark runs are handed off to background threads to ensure
the HTTP request listener remains non-blocking and responsive.
"""

from __future__ import annotations
import argparse
import json
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from benchmark import BenchmarkManager

# Shared application benchmark manager
BENCHMARK_MGR = BenchmarkManager()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
MAX_BODY_BYTES = 64 * 1024  # 64 KB safety limit
EVIDENCE_FILE = os.path.join(BASE_DIR, "benchmark_run_evidence.json")


def preload_existing_evidence() -> None:
    """Pre-populates results from verified benchmark evidence if available."""
    if os.path.isfile(EVIDENCE_FILE):
        try:
            with open(EVIDENCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "latest_comparison" in data and data["latest_comparison"]:
                BENCHMARK_MGR.latest_comparison = data["latest_comparison"]
            if "all_completed_runs" in data and data["all_completed_runs"]:
                BENCHMARK_MGR.all_completed_runs = list(data["all_completed_runs"])
            if "latest_single_result" in data and data["latest_single_result"]:
                BENCHMARK_MGR.latest_single_result = data["latest_single_result"]
            print("[INFO] Preloaded benchmark comparison evidence into memory.")
        except Exception as exc:
            print(f"[WARN] Could not preload evidence: {exc}")


preload_existing_evidence()


def validate_settings(data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    """Validates benchmark parameters according to OS project limits."""
    try:
        mode = str(data.get("mode", "bounded_pool")).strip().lower()
        if mode not in ("baseline", "bounded_pool"):
            return False, {}, "Invalid mode. Must be 'baseline' or 'bounded_pool'."

        worker_count = int(data.get("worker_count", 8))
        if not (1 <= worker_count <= 32):
            return False, {}, "Worker count must be an integer between 1 and 32."

        queue_capacity = int(data.get("queue_capacity", 100))
        if not (1 <= queue_capacity <= 2000):
            return False, {}, "Queue capacity must be an integer between 1 and 2000."

        request_count = int(data.get("request_count", 200))
        if not (10 <= request_count <= 2000):
            return False, {}, "Request count must be an integer between 10 and 2000."

        producer_concurrency = int(data.get("producer_concurrency", 10))
        if not (1 <= producer_concurrency <= 100):
            return False, {}, "Producer concurrency must be an integer between 1 and 100."

        simulated_io_ms = float(data.get("simulated_io_ms", 50.0))
        if not (0.0 <= simulated_io_ms <= 5000.0):
            return False, {}, "Simulated I/O wait must be between 0 and 5000 milliseconds."

        validated = {
            "mode": mode,
            "worker_count": worker_count,
            "queue_capacity": queue_capacity,
            "request_count": request_count,
            "producer_concurrency": producer_concurrency,
            "simulated_io_ms": simulated_io_ms
        }
        return True, validated, ""
    except (ValueError, TypeError) as exc:
        return False, {}, f"Invalid configuration payload: {exc}"


class RequestHandler(BaseHTTPRequestHandler):
    """Handles static web requests and benchmark REST API calls."""

    server_version = "OS-ThreadServer/1.0"

    def _send_json(self, status_code: int, data: Any, headers: Optional[Dict[str, str]] = None) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, status_code: int, message: str) -> None:
        self._send_json(status_code, {"error": message})

    def _read_json_body(self) -> Tuple[bool, Any, str]:
        content_length_header = self.headers.get("Content-Length")
        if not content_length_header:
            return False, None, "Missing Content-Length header."
        try:
            content_length = int(content_length_header)
        except ValueError:
            return False, None, "Invalid Content-Length header."

        if content_length > MAX_BODY_BYTES:
            return False, None, f"Request body too large ({content_length} bytes). Max is {MAX_BODY_BYTES} bytes."

        body_bytes = self.rfile.read(content_length)
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
            return True, parsed, ""
        except json.JSONDecodeError as exc:
            return False, None, f"Malformed JSON: {exc.msg}"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        # REST API endpoints
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {
                "status": "healthy",
                "version": "1.0.0",
                "title": "Thread Management for High-Performance Web Servers"
            })
            return

        if path == "/api/status":
            status = BENCHMARK_MGR.get_status()
            self._send_json(HTTPStatus.OK, status)
            return

        if path == "/api/results":
            self._send_json(HTTPStatus.OK, {
                "latest_comparison": BENCHMARK_MGR.latest_comparison,
                "latest_single_result": BENCHMARK_MGR.latest_single_result,
                "all_completed_runs": BENCHMARK_MGR.all_completed_runs
            })
            return

        if path == "/api/run-tests":
            import subprocess
            try:
                test_proc = subprocess.run(
                    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                    cwd=BASE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=20
                )
                raw_out = (test_proc.stdout or "") + (test_proc.stderr or "")
                self._send_json(HTTPStatus.OK, {
                    "success": test_proc.returncode == 0,
                    "returncode": test_proc.returncode,
                    "output": raw_out.strip()
                })
            except Exception as exc:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error running tests: {exc}")
            return

        if path == "/api/export":
            export_payload = BENCHMARK_MGR.export_data()
            filename = f"benchmark_results_{int(export_payload['timestamp_epoch'])}.json"
            headers = {
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
            self._send_json(HTTPStatus.OK, export_payload, headers=headers)
            return

        # Static file serving
        if path == "/" or path == "/index.html":
            file_path = os.path.join(STATIC_DIR, "index.html")
        elif path.startswith("/static/"):
            rel_path = os.path.relpath(path, "/static/")
            file_path = os.path.abspath(os.path.join(STATIC_DIR, rel_path))
            # Path traversal prevention
            if not file_path.startswith(STATIC_DIR):
                self._send_error_json(HTTPStatus.FORBIDDEN, "Forbidden access")
                return
        else:
            self._send_error_json(HTTPStatus.NOT_FOUND, f"Route not found: {path}")
            return

        if not os.path.isfile(file_path):
            self._send_error_json(HTTPStatus.NOT_FOUND, "Static file not found.")
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if "text" in mime_type or "javascript" in mime_type else mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except OSError as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error reading file: {exc}")

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/benchmark":
            ok, body, err = self._read_json_body()
            if not ok:
                self._send_error_json(HTTPStatus.BAD_REQUEST, err)
                return

            valid, settings, val_err = validate_settings(body)
            if not valid:
                self._send_error_json(HTTPStatus.BAD_REQUEST, val_err)
                return

            started, start_msg = BENCHMARK_MGR.start_single_benchmark(
                mode=settings["mode"],
                request_count=settings["request_count"],
                producer_concurrency=settings["producer_concurrency"],
                worker_count=settings["worker_count"],
                queue_capacity=settings["queue_capacity"],
                simulated_io_ms=settings["simulated_io_ms"]
            )
            if not started:
                self._send_error_json(HTTPStatus.CONFLICT, start_msg)
                return

            self._send_json(HTTPStatus.ACCEPTED, {"message": start_msg, "settings": settings})
            return

        if path == "/api/compare":
            ok, body, err = self._read_json_body()
            if not ok:
                self._send_error_json(HTTPStatus.BAD_REQUEST, err)
                return

            valid, settings, val_err = validate_settings(body)
            if not valid:
                self._send_error_json(HTTPStatus.BAD_REQUEST, val_err)
                return

            started, start_msg = BENCHMARK_MGR.start_comparison(
                request_count=settings["request_count"],
                producer_concurrency=settings["producer_concurrency"],
                worker_count=settings["worker_count"],
                queue_capacity=settings["queue_capacity"],
                simulated_io_ms=settings["simulated_io_ms"]
            )
            if not started:
                self._send_error_json(HTTPStatus.CONFLICT, start_msg)
                return

            self._send_json(HTTPStatus.ACCEPTED, {"message": start_msg, "settings": settings})
            return

        if path == "/api/reset":
            success, msg = BENCHMARK_MGR.reset_results()
            if not success:
                self._send_error_json(HTTPStatus.CONFLICT, msg)
                return
            self._send_json(HTTPStatus.OK, {"message": msg})
            return

        self._send_error_json(HTTPStatus.NOT_FOUND, f"Endpoint not found: {path}")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default verbose request logging in console to keep terminal clean."""
        pass


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    server_address = (host, port)
    try:
        httpd = HTTPServer(server_address, RequestHandler)
    except OSError as exc:
        print(f"\n[ERROR] Could not bind server to {host}:{port}.")
        print(f"Details: {exc}")
        print("Tip: If port is already in use, run with another port, e.g.:")
        print("    python app.py --port 8081\n")
        sys.exit(1)

    print("=" * 68)
    print("   THREAD MANAGEMENT FOR HIGH-PERFORMANCE WEB SERVERS")
    print("   Operating Systems Project Demonstration Engine")
    print("=" * 68)
    print(f" * Server running at: http://{host}:{port}/")
    print(f" * Bound strictly to localhost ({host}) for safety.")
    print(" * Press Ctrl+C to stop the server gracefully.")
    print("=" * 68)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Graceful shutdown initiated by user.")
    finally:
        httpd.server_close()
        print("[INFO] Server stopped safely.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Thread Management Web Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
