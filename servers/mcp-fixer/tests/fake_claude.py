"""A stand-in for `claude -p` in the runner tests. The behavior is chosen with --mode; every
other argument is recorded (they are what the runner passed) together with stdin."""
import argparse
import json
import os
import sys
import time

parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument("--mode", default="ok")
parser.add_argument("--record")
parser.add_argument("--pid-file")
args, rest = parser.parse_known_args()

prompt = sys.stdin.buffer.read().decode("utf-8")
if args.record:
    with open(args.record, "w", encoding="utf-8") as handle:
        json.dump({"argv": rest, "stdin": prompt}, handle)
if args.pid_file:
    with open(args.pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))

if args.mode == "fail":
    sys.stderr.write("boom happened\nsecond line\n")
    sys.exit(3)
if args.mode == "hang":
    time.sleep(60)
if args.mode == "huge":
    sys.stdout.write("x" * 1000000)
    sys.exit(0)
if args.mode == "badbytes":
    sys.stdout.buffer.write(b'{"tool": "get_item"} \xff\xfe')
    sys.exit(0)
sys.stdout.write('{"tool": "get_item"}\n')
