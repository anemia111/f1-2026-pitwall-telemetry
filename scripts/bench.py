"""Loopback benchmark with a separate 24-car 60 Hz demo sender."""
import argparse
from collections import Counter
from pathlib import Path
import socket
import subprocess
import signal
import sys
import tempfile
from threading import Thread
from time import monotonic, sleep
from urllib.request import urlopen
import json

import uvicorn

from pitwall.server import create_app
from pitwall.service import Settings


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    http, udp = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="apex-bench-") as directory:
        db = Path(directory) / "bench.sqlite3"
        settings = Settings(mode="DEMO", udp_host="127.0.0.1", udp_port=udp)
        server = uvicorn.Server(uvicorn.Config(create_app(settings, db), host="127.0.0.1", port=http,
                                               log_level="warning", access_log=False))
        thread = Thread(target=server.run, daemon=True)
        thread.start()
        sender = None
        frames = Counter()
        peak = 0.
        try:
            def read() -> dict:
                with urlopen(f"http://127.0.0.1:{http}/api/state", timeout=3) as r:
                    return json.load(r)

            end = monotonic() + 15
            while True:
                try:
                    if read().get("connection"):
                        break
                except OSError:
                    pass
                if monotonic() >= end or not thread.is_alive():
                    raise RuntimeError("server did not start")
                sleep(.1)
            creation = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            sender = subprocess.Popen([sys.executable, "-m", "pitwall.demo", "--port", str(udp), "--hz", "60"],
                                      cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=creation)
            end = monotonic() + args.seconds
            start = monotonic()
            while monotonic() < end:
                state = read()
                frames[len(state["cars"])] += 1
                peak = max(peak, state["connection"]["peakMs"])
                if sender.poll() is not None:
                    raise RuntimeError("sender exited")
                sleep(.2)
            elapsed = monotonic() - start
            state = read()
            report = {
                "seconds": round(elapsed, 2), "nominalHz": 60, "cars": len(state["cars"]),
                "packets": state["counts"]["valid"], "packetsPerSecond": round(state["counts"]["valid"] / elapsed, 1),
                "invalid": state["counts"]["invalid"], "frameIdGaps": state["counts"]["frameGaps"],
                "peakReceiveCallbackMs": peak, "archiveDrops": state["connection"]["archiveDrops"],
                "archiveError": state["connection"]["archiveError"],
                "observationsByCarCount": dict(frames),
                "archiveBytes": sum(p.stat().st_size for p in Path(directory).iterdir()),
            }
            print(json.dumps(report, indent=2))
            if (report["cars"] != 24 or not state["online"] or report["invalid"] or
                report["archiveDrops"] or report["archiveError"] or not report["packets"]):
                raise SystemExit(1)
        finally:
            try:
                if sender and sender.poll() is None:
                    if sys.platform == "win32":
                        sender.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        sender.terminate()
                    sender.wait(timeout=10)
            finally:
                server.should_exit = True
                thread.join(timeout=15)
                if thread.is_alive():
                    raise RuntimeError("server did not finish closing the archive")


if __name__ == "__main__":
    main()
