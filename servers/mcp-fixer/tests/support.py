"""Shared test setup: puts src/ on sys.path and offers a few helpers."""
import os
import subprocess
import sys
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SRC = ROOT / "src"
FAKE_SERVER = TESTS / "fake_server.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def process_alive(pid):
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_until_gone(pid, seconds=5.0):
    """True when the process is gone within `seconds`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.05)
    return not process_alive(pid)
