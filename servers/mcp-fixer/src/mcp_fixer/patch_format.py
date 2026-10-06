"""The patch file: loading, validating and applying it. Standard library only."""
import copy
import hashlib
import json
import math
import re
from pathlib import Path

PATCH_VERSION = 1
TOP_KEYS = frozenset({"patchVersion", "source", "notes", "tools"})
ENTRY_KEYS = frozenset(
    {"base", "rename", "description", "params", "required", "review", "todo", "context"}
)
PARAM_KEYS = frozenset({"description", "type", "enum", "default"})
_BASE = re.compile(r"^[0-9a-f]{64}$")


class PatchError(Exception):
    """A problem with a patch file, reported as one line."""


def fingerprint(tool):
    """SHA-256 of the tool's canonical JSON: how a patch notices that a tool has changed."""
    text = json.dumps(tool, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _is_strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_scalar(value):
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (str, int, bool))


def _check_params(name, params):
    where = f"tool {name!r}: "
    if not isinstance(params, dict):
        raise PatchError(where + "params must be an object")
    for pname, changes in params.items():
        label = f"params[{pname!r}]"
        if not isinstance(changes, dict):
            raise PatchError(where + f"{label} must be an object")
        for key in changes:
            if key not in PARAM_KEYS:
                raise PatchError(where + f"{label} has unknown field {key!r}")
        if "description" in changes and not isinstance(changes["description"], str):
            raise PatchError(where + f"{label}.description must be a string")
        if "type" in changes and not (
            isinstance(changes["type"], str) or _is_strings(changes["type"])
        ):
            raise PatchError(where + f"{label}.type must be a string or a list of strings")
        if "enum" in changes:
            values = changes["enum"]
            if not (isinstance(values, list) and values and all(_is_scalar(v) for v in values)):
                raise PatchError(
                    where + f"{label}.enum must be a non-empty list of strings, numbers, booleans or null"
                )


def _check_todo(where, todo):
    if not isinstance(todo, list):
        raise PatchError(where + "todo must be a list")
    for index, item in enumerate(todo):
        ok = (
            isinstance(item, dict)
            and set(item) <= {"rule", "param", "hint"}
            and isinstance(item.get("rule"), str)
            and all(isinstance(item[key], str) for key in ("param", "hint") if key in item)
        )
        if not ok:
            raise PatchError(
                where + f"todo[{index}] must be an object with a string rule, and optional string param and hint"
            )


def _check_entry(name, entry):
    where = f"tool {name!r}: "
    if not isinstance(entry, dict):
        raise PatchError(where + "must be an object")
    for key in entry:
        if key not in ENTRY_KEYS:
            raise PatchError(where + f"unknown field {key!r}")
    if "base" in entry and not (isinstance(entry["base"], str) and _BASE.match(entry["base"])):
        raise PatchError(where + "base must be a 64-character lowercase hex SHA-256")
    if "rename" in entry:
        new = entry["rename"]
        if not (isinstance(new, str) and new and new != name):
            raise PatchError(where + "rename must be a non-empty string different from the tool's name")
    if "description" in entry and not isinstance(entry["description"], str):
        raise PatchError(where + "description must be a string")
    if "params" in entry:
        _check_params(name, entry["params"])
    if "required" in entry:
        required = entry["required"]
        if not (_is_strings(required) and len(set(required)) == len(required)):
            raise PatchError(where + "required must be a list of unique strings")
    if "review" in entry and not _is_strings(entry["review"]):
        raise PatchError(where + "review must be a list of strings")
    if "todo" in entry:
        _check_todo(where, entry["todo"])
    if "context" in entry and not isinstance(entry["context"], dict):
        raise PatchError(where + "context must be an object")


def validate_patch(data):
    if not isinstance(data, dict):
        raise PatchError("the patch must be a JSON object")
    for key in data:
        if key not in TOP_KEYS:
            raise PatchError(f"unknown field {key!r} in the patch")
    version = data.get("patchVersion")
    if type(version) is not int or version != PATCH_VERSION:
        raise PatchError(f"patchVersion must be {PATCH_VERSION}")
    if "source" in data and not isinstance(data["source"], dict):
        raise PatchError("source must be an object")
    if "notes" in data and not _is_strings(data["notes"]):
        raise PatchError("notes must be a list of strings")
    tools = data.get("tools")
    if not isinstance(tools, dict):
        raise PatchError("tools must be an object")
    renames = {}
    for name, entry in tools.items():
        _check_entry(name, entry)
        new = entry.get("rename")
        if new is not None:
            if new in renames:
                raise PatchError(f"tools {renames[new]!r} and {name!r} are both renamed to {new!r}")
            renames[new] = name
    for new, name in renames.items():
        if new in tools:
            raise PatchError(f"tool {name!r} is renamed to {new!r}, which is another tool in the patch")
    return data


def load_patch(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise PatchError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PatchError(f"{path} is not UTF-8 text") from None
    try:
        data = json.loads(text)
    except RecursionError:
        raise PatchError(f"{path} is not valid JSON (nested too deeply)") from None
    except ValueError as exc:
        raise PatchError(f"{path} is not valid JSON ({exc})") from None
    try:
        return validate_patch(data)
    except PatchError as exc:
        raise PatchError(f"{path}: {exc}") from None


def apply_entry(tool, entry):
    """A modified deep copy of `tool` with `entry` applied, and the warnings it produced."""
    new = copy.deepcopy(tool)
    warnings = []
    name = tool.get("name")
    if "description" in entry:
        new["description"] = entry["description"]
    schema = new.get("inputSchema")
    props = schema.get("properties") if isinstance(schema, dict) else None
    if entry.get("params"):
        if not isinstance(props, dict):
            warnings.append(f"tool {name!r} has no input properties; skipped its parameter changes")
        else:
            for pname, changes in entry["params"].items():
                if pname not in props:
                    warnings.append(f"parameter {pname!r} is not in tool {name!r}; skipped")
                    continue
                if not isinstance(props[pname], dict):
                    props[pname] = {}
                for key, value in changes.items():
                    props[pname][key] = copy.deepcopy(value)
    if "required" in entry:
        if not isinstance(props, dict):
            warnings.append(f"tool {name!r} has no input properties; skipped its required list")
        else:
            kept = []
            for required in entry["required"]:
                if required in props:
                    kept.append(required)
                else:
                    warnings.append(
                        f"required name {required!r} is not a parameter of tool {name!r}; dropped"
                    )
            schema["required"] = kept
    if "rename" in entry:
        new["name"] = entry["rename"]
    return new, warnings
