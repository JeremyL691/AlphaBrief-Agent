from __future__ import annotations

import argparse
import atexit
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings


def _is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex((host, port)) != 0


def ensure_port_available(host: str, port: int, service_name: str) -> None:
    if not _is_port_available(host, port):
        raise RuntimeError(
            f"{service_name} cannot start because port {port} on {host} is already in use. "
            f"Close the existing process or change the configured port."
        )


def build_process_commands(python_executable: str) -> tuple[list[str], list[str]]:
    api_cmd = [
        python_executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        settings.api_host,
        "--port",
        str(settings.api_port),
    ]
    dashboard_cmd = [
        python_executable,
        "-m",
        "streamlit",
        "run",
        "dashboard/streamlit_app.py",
        "--server.headless",
        "true",
        "--server.port",
        str(settings.dashboard_port),
        "--browser.gatherUsageStats",
        "false",
    ]
    return api_cmd, dashboard_cmd


def wait_for_url(url: str, timeout_sec: float, label: str) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
    raise RuntimeError(f"{label} did not become ready within {timeout_sec:.0f} seconds.")


def _print_log_tail(label: str, path: Path, lines: int = 30) -> None:
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-lines:]
    except OSError:
        return
    print(f"\n--- last {len(tail)} lines of {label} log ({path.name}) ---", file=sys.stderr)
    for line in tail:
        print(line.rstrip(), file=sys.stderr)
    print("--- end log ---\n", file=sys.stderr)


def _spawn_process(command: list[str], env: dict[str, str], log_path: Path) -> subprocess.Popen:
    log_file = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    atexit.register(log_file.close)
    return process


def start_services(open_browser: bool = True) -> None:
    settings.ensure_dirs()
    ensure_port_available(settings.api_host, settings.api_port, "API")
    ensure_port_available("127.0.0.1", settings.dashboard_port, "Dashboard")

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    api_log = settings.logs_dir / f"api-{timestamp}.log"
    dashboard_log = settings.logs_dir / f"dashboard-{timestamp}.log"
    env = os.environ.copy()
    env["ALPHABRIEF_API_BASE_URL"] = settings.api_base_url

    api_cmd, dashboard_cmd = build_process_commands(sys.executable)
    api_proc = _spawn_process(api_cmd, env=env, log_path=api_log)
    dashboard_proc = _spawn_process(dashboard_cmd, env=env, log_path=dashboard_log)

    try:
        wait_for_url(f"{settings.api_base_url}/health", timeout_sec=45, label="API")
        wait_for_url(settings.dashboard_url, timeout_sec=60, label="Dashboard")
        if open_browser:
            webbrowser.open(settings.dashboard_url)
        print(f"AlphaBrief Agent is ready at {settings.dashboard_url}")
        print(f"API log: {api_log}")
        print(f"Dashboard log: {dashboard_log}")

        while True:
            api_code = api_proc.poll()
            dash_code = dashboard_proc.poll()
            if api_code is not None or dash_code is not None:
                crashed_logs = []
                if api_code is not None:
                    crashed_logs.append(("API", api_log))
                if dash_code is not None:
                    crashed_logs.append(("Dashboard", dashboard_log))
                for label, path in crashed_logs:
                    _print_log_tail(label, path)
                raise RuntimeError(
                    "A service exited unexpectedly. "
                    f"API exit={api_code}, Dashboard exit={dash_code}. "
                    f"Full logs in {settings.logs_dir}."
                )
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping AlphaBrief Agent...")
    finally:
        for process in (api_proc, dashboard_proc):
            if process.poll() is None:
                process.terminate()
        for process in (api_proc, dashboard_proc):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(prog="alphabrief-launcher")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        start_services(open_browser=not args.no_browser)
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
