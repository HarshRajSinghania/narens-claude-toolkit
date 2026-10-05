"""A tiny stdio MCP server for the client tests. The behavior is chosen with --mode."""
import argparse
import json
import os
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--mode", default="normal")
parser.add_argument("--tools")
parser.add_argument("--page-size", type=int, default=0)
parser.add_argument("--pid-file")
args = parser.parse_args()

if args.pid_file:
    with open(args.pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))

TOOLS = []
if args.tools:
    with open(args.tools, encoding="utf-8") as handle:
        TOOLS = json.load(handle)


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def tools_page(params):
    cursor = (params or {}).get("cursor")
    start = int(cursor) if cursor else 0
    if args.mode == "forever":
        return {
            "tools": [{"name": f"t{start}", "description": "x" * 25, "inputSchema": {"type": "object"}}],
            "nextCursor": str(start + 1),
        }
    if args.page_size:
        result = {"tools": TOOLS[start:start + args.page_size]}
        if start + args.page_size < len(TOOLS):
            result["nextCursor"] = str(start + args.page_size)
        return result
    return {"tools": TOOLS}


if args.mode == "exit":
    sys.exit(4)
if args.mode == "noisy":
    for junk in ("Fake server starting up...", "{not json", "[1, 2, 3]", ""):
        sys.stdout.write(junk + "\n")
    sys.stdout.flush()

waiting_for_ping = False
held = None

for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    if not isinstance(message, dict):
        continue
    method = message.get("method")
    mid = message.get("id")
    if method is None:
        if mid == "ping-1" and waiting_for_ping:
            waiting_for_ping = False
            if held is not None:
                send({"jsonrpc": "2.0", "id": held[0], "result": tools_page(held[1])})
                held = None
        continue
    if method == "initialize":
        if args.mode == "hang":
            time.sleep(60)
        if args.mode == "error":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unsupported protocol version"}})
            continue
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-server", "version": "1.2.3"},
                },
            }
        )
        if args.mode == "crash":
            sys.exit(3)
    elif method == "notifications/initialized":
        if args.mode == "ping":
            waiting_for_ping = True
            send({"jsonrpc": "2.0", "id": "ping-1", "method": "ping"})
    elif method == "tools/list":
        if args.mode == "hang-list":
            time.sleep(60)
        if args.mode == "slow":
            time.sleep(0.2)
        if args.mode == "badresult":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": "nope"}})
            continue
        if waiting_for_ping:
            held = (mid, message.get("params"))
            continue
        send({"jsonrpc": "2.0", "id": mid, "result": tools_page(message.get("params"))})
