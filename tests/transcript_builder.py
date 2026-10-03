"""Build synthetic Claude Code transcript trees for tests (real field names, no real text)."""
import json
from pathlib import Path

SECRET = "SECRET-PROMPT-TEXT"
DEFAULT_TS = "2026-10-01T10:00:00.000Z"


def assistant(mid, model="claude-sonnet-5-5", *, inp=0, out=0, read=0, write5=0, write1=0,
              ts=DEFAULT_TS, breakdown=True, sidechain=False):
    usage = {
        "input_tokens": inp,
        "cache_creation_input_tokens": write5 + write1,
        "cache_read_input_tokens": read,
        "output_tokens": out,
    }
    if breakdown:
        usage["cache_creation"] = {
            "ephemeral_5m_input_tokens": write5,
            "ephemeral_1h_input_tokens": write1,
        }
    return {
        "type": "assistant",
        "timestamp": ts,
        "isSidechain": sidechain,
        "message": {
            "id": mid,
            "model": model,
            "role": "assistant",
            "content": [{"type": "text", "text": SECRET}],
            "usage": usage,
        },
    }


def user(ts=DEFAULT_TS):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": SECRET}}


def write_jsonl(path, records, raw_tail=()):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r) + "\n" for r in records) + "".join(line + "\n" for line in raw_tail)
    path.write_bytes(text.encode("utf-8"))


def add_session(projects, slug, session_id, records, subagents=()):
    """Write <projects>/<slug>/<session_id>.jsonl and one file (plus meta) per subagent."""
    pdir = Path(projects) / slug
    write_jsonl(pdir / f"{session_id}.jsonl", [user()] + list(records))
    for sub in subagents:
        base = str(pdir / session_id / "subagents" / f"agent-{sub['id']}")
        write_jsonl(base + ".jsonl", [user(sub.get("ts", DEFAULT_TS))] + list(sub["records"]))
        if sub.get("meta", True):
            meta = {
                "agentType": sub.get("type", "general-purpose"),
                "description": sub.get("description", "a task"),
                "toolUseId": "toolu_x",
                "spawnDepth": 1,
                "model": sub.get("alias", "sonnet"),
            }
            Path(base + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return pdir
