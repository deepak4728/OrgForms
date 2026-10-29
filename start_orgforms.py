"""Start the local prototype and open its browser after Django is ready."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser


PROJECT_ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if sys.version_info < (3, 12):
        print("OrgForms requires Python 3.12 or later.", flush=True)
        return 1

    # Fail clearly instead of opening some unrelated application using this port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            print(
                f"Cannot use port {args.port}. OrgForms may already be running.\n"
                "Use its existing server window, or close the application using this port.",
                flush=True,
            )
            return 1

    url = f"http://127.0.0.1:{args.port}/"
    environment = os.environ.copy()
    # This launcher is deliberately a loopback-only development convenience.
    # Override production HTTPS settings through DEBUG for this child process only.
    environment["DJANGO_DEBUG"] = "true"
    environment["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1"
    environment["PYTHONUNBUFFERED"] = "1"
    print(
        f"Starting OrgForms at {url}\n"
        "Keep this window open while using the app. Press Ctrl+C to stop.\n"
        "This prototype launcher is for this computer only; internet access is disabled.",
        flush=True,
    )
    server = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "manage.py"), "runserver",
         f"127.0.0.1:{args.port}", "--noreload"],
        cwd=PROJECT_ROOT,
        env=environment,
    )
    try:
        deadline = time.monotonic() + 30
        # Ignore system HTTP proxies when probing this machine's own server.
        opener = build_opener(ProxyHandler({}))
        while time.monotonic() < deadline:
            if server.poll() is not None:
                print("OrgForms could not start. See the error above.", flush=True)
                return server.returncode or 1
            try:
                with opener.open(url, timeout=1) as response:
                    ready = response.status == 200
            except (OSError, URLError):
                ready = False
            if ready:
                print(f"OrgForms is ready. Open {url}", flush=True)
                if not args.no_browser:
                    try:
                        if not webbrowser.open(url):
                            print("Could not open a browser automatically. Use the link above.", flush=True)
                    except webbrowser.Error:
                        print("Could not open a browser automatically. Use the link above.", flush=True)
                return server.wait()
            time.sleep(0.25)
        print("OrgForms did not become ready within 30 seconds. See the server output above.", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\nStopping OrgForms...", flush=True)
        return 0
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
