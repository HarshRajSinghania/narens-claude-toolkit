"""Build a patch from a tool list and its lint findings. Pure; standard library only."""
import json
import re

from . import patch_format, rules, score as score_module

LIMIT = rules.THRESHOLDS["description_max_chars"]
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_ELLIPSIS = "…"


def trim_description(text, limit=LIMIT):
    """`text` with whitespace collapsed and cut to at most `limit` characters.

    Whole sentences are kept while they fit; when even the first does not, the text is cut at a
    word boundary and ends with an ellipsis.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    kept = ""
    for sentence in _SENTENCE_BREAK.split(collapsed):
        candidate = sentence if not kept else kept + " " + sentence
        if len(candidate) > limit:
            break
        kept = candidate
    if kept:
        return kept
    cut = collapsed[: limit - 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip() + _ELLIPSIS


def _context(tool):
    description = tool.get("description")
    schema = tool.get("inputSchema")
    props = schema.get("properties") if isinstance(schema, dict) else None
    params = {}
    if isinstance(props, dict):
        for name, prop in props.items():
            text = prop.get("description") if isinstance(prop, dict) else None
            params[name] = text if isinstance(text, str) else ""
    return {"description": description if isinstance(description, str) else "", "params": params}


def _build_entry(tool, findings):
    params = {}
    review = []
    todo = []
    description = None
    for found in findings:
        rule = found["rule"]
        if rule == "P003":
            values = found["data"]["values"]
            params.setdefault(found["param"], {})["enum"] = values
            review.append(
                f"parameter '{found['param']}': enum inferred from its description "
                f"({len(values)} values); check the list is complete"
            )
        elif rule == "D003":
            original = tool["description"]
            description = trim_description(original)
            review.append(f"description trimmed from {len(original)} to {len(description)} characters")
        else:
            item = {"rule": rule}
            if found["param"]:
                item["param"] = found["param"]
            hint = found["fix"]
            if rule == "D004":
                hint = f"{found['message']}: {found['fix']}"
            item["hint"] = hint
            todo.append(item)
    if description is None and not (params or review or todo):
        return None
    entry = {"base": patch_format.fingerprint(tool)}
    if description is not None:
        entry["description"] = description
    if params:
        entry["params"] = params
    if review:
        entry["review"] = review
    if todo:
        entry["todo"] = todo
    entry["context"] = _context(tool)
    return entry


def generate_patch(tools, source=None):
    first = {}
    duplicates = []
    unique = []
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool["name"]:
            if tool["name"] in first:
                if tool["name"] not in duplicates:
                    duplicates.append(tool["name"])
                continue  # a later duplicate must not lend its findings to the first tool
            first[tool["name"]] = tool
        unique.append(tool)
    # Server-level notes come from the full list; tool-level findings from the unique tools only.
    notes = [f["message"] for f in score_module.score_tools(tools, source)["findings"] if f["tool"] is None]
    by_tool = {}
    for found in score_module.score_tools(unique, source)["findings"]:
        if found["tool"] is not None:
            by_tool.setdefault(found["tool"], []).append(found)
    if duplicates:
        notes.append("duplicate tool names cannot be patched separately: " + ", ".join(sorted(duplicates)))
    entries = {}
    for name, tool in first.items():
        entry = _build_entry(tool, by_tool.get(name, []))
        if entry is not None:
            entries[name] = entry
    patch = {"patchVersion": patch_format.PATCH_VERSION}
    if source and source.get("kind") == "stdio":
        patch["source"] = {
            "serverName": source.get("serverName"),
            "serverVersion": source.get("serverVersion"),
        }
    if notes:
        patch["notes"] = notes
    patch["tools"] = entries
    return patch


def render_patch(patch):
    return json.dumps(patch, indent=2, ensure_ascii=False) + "\n"
