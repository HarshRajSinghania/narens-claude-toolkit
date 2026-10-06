"""A tiny stdio MCP server for the client tests. The behavior is chosen with --mode."""
import argparse
import json
import os
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--mode", default="normal")
parser.add_argument("--tools")
parser.add_argument("--page-size", type=int, default=0)
parser.add_argument("--pid-file")
parser.add_argument("--child-pid-file")
args = parser.parse_args()

# Keep "\n" as written: Windows text mode would turn it into "\r\n" and hide byte-level bugs.
sys.stdout.reconfigure(newline="\n")

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


if args.mode in ("grandchild", "grandchild-exit"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    if args.child_pid_file:
        with open(args.child_pid_file, "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
    if args.mode == "grandchild-exit":
        sys.exit(4)
if args.mode == "exit":
    sys.exit(4)
if args.mode == "deep":
    sys.stdout.write("[" * 5000 + "\n")
    sys.stdout.flush()
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
        if mid == "ping-1" and waiting_for_ping and message.get("result") == {}:
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
        if args.mode == "multiline-error":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": "first line\nsecond line\n" + "y" * 3000}})
            continue
        if args.mode == "no-message-error":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32001}})
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
        if args.mode == "odd-bytes":
            sys.stdout.write('{"method":"notifications/message",   "params":{"level":"info","data":"caf\\u00e9"},"jsonrpc":"2.0"}\n')
            sys.stdout.flush()
        if args.mode == "ping-flood":
            for number in range(100000):
                send({"jsonrpc": "2.0", "id": f"flood-{number}", "method": "ping"})
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
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if name not in {t.get("name") for t in TOOLS if isinstance(t, dict)}:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}})
        else:
            shown = json.dumps(params.get("arguments", {}), sort_keys=True)
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"called {name} with {shown}"}], "isError": False}})
    elif method == "resources/list" and args.mode == "odd-bytes":
        sys.stdout.write(' { "jsonrpc" : "2.0" , "result" : {"b":1,"a":"caf\\u00e9 \\/ \\ud83d\\ude00"},   "id" : ' + json.dumps(mid) + " }\n")
        sys.stdout.flush()
    elif method == "resources/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"resources": []}})

if args.mode == "hang-on-eof":
    time.sleep(60)
