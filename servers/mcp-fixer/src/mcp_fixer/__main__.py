import os
import sys

from .cli import main

code = main()
# The wrapper's client-reading thread may still be blocked on stdin; leaving through os._exit
# avoids a hang or a shutdown error from that daemon thread. Output is flushed first.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.flush()
    except (OSError, ValueError):
        pass
os._exit(code)
