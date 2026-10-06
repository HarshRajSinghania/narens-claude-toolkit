"""The benchmark: tasks file, patched view, trials and the report. Standard library only."""
import json
import math
import random
from pathlib import Path

from . import bench_prompts, bench_stats, patch_format
from .report import _safe
from .runners import RunnerError
from .score import score_tools
from .wrap import Router

TASKS_VERSION = 1
DISCLAIMER = (
    "This measures whether a drop could be detected on these generated tasks; "
    "it does not show the patch improves tool selection."
)
_MAX_NOTE = 300


class BenchError(Exception):
    """A problem with the benchmark's inputs, reported as one line."""


class TasksError(BenchError):
    """A problem with the tasks file or with generating it."""


def _clip(text):
    text = _safe(text)
    return text if len(text) <= _MAX_NOTE else text[: _MAX_NOTE - 1] + "…"


# --- tools -------------------------------------------------------------------------------------
def valid_tools(tools):
    """The first tool dict with a non-empty string name for each name."""
    seen = set()
    out = []
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool["name"]:
            if tool["name"] not in seen:
                seen.add(tool["name"])
                out.append(tool)
    return out


def tools_fingerprint(tools):
    return patch_format.fingerprint(valid_tools(tools))


# --- the tasks file ----------------------------------------------------------------------------
def validate_tasks(data):
    if not isinstance(data, dict):
        raise TasksError("the tasks file must be a JSON object")
    for key in data:
        if key not in ("tasksVersion", "source", "tasks"):
            raise TasksError(f"unknown field {_clip(repr(key))} in the tasks file")
    if type(data.get("tasksVersion")) is not int or data["tasksVersion"] != TASKS_VERSION:
        raise TasksError(f"tasksVersion must be {TASKS_VERSION}")
    if "source" in data and not isinstance(data["source"], dict):
        raise TasksError("source must be an object")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise TasksError("tasks must be a non-empty list")
    seen = set()
    for index, task in enumerate(tasks):
        where = f"task {index}"
        if not isinstance(task, dict):
            raise TasksError(f"{where}: must be an object")
        for key in task:
            if key not in ("id", "request", "expected"):
                raise TasksError(f"{where}: unknown field {_clip(repr(key))}")
        for key in ("id", "request", "expected"):
            if not (isinstance(task.get(key), str) and task[key].strip()):
                raise TasksError(f"{where}: {key} must be a non-empty string")
        if task["id"] in seen:
            raise TasksError(f"{where}: duplicate id {_clip(repr(task['id']))}")
        seen.add(task["id"])
    return data


def load_tasks(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise TasksError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TasksError(f"{path} is not UTF-8 text") from None
    try:
        data = json.loads(text)
    except RecursionError:
        raise TasksError(f"{path} is not valid JSON (nested too deeply)") from None
    except ValueError as exc:
        raise TasksError(f"{path} is not valid JSON ({exc})") from None
    try:
        return validate_tasks(data)
    except TasksError as exc:
        raise TasksError(f"{path}: {exc}") from None


def render_tasks(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def check_tasks(data, tools):
    """Warnings about the tasks file; raises BenchError when a task cannot be scored."""
    names = {t["name"] for t in valid_tools(tools)}
    if not names:
        raise BenchError("the tool list has no usable tools")
    for task in data["tasks"]:
        if task["expected"] not in names:
            raise BenchError(
                f"task {_clip(repr(task['id']))} expects {_clip(repr(task['expected']))}, "
                "which is not a tool in the original list"
            )
    warnings = []
    wanted = data.get("source", {}).get("toolsFingerprint")
    if wanted is not None and wanted != tools_fingerprint(tools):
        warnings.append("the tasks were written for different tools than the ones being benchmarked")
    return warnings


def call_with_retry(runner, prompt):
    """(text, error, attempts): one retry after a RunnerError, then give up."""
    attempts = 0
    error = None
    for _ in range(2):
        attempts += 1
        try:
            return runner.complete(prompt), None, attempts
        except RunnerError as exc:
            error = str(exc)
    return None, error, attempts


def generate_tasks(tools, runner, per_tool, source=None, log=None):
    log = log or (lambda text: None)
    tools = valid_tools(tools)
    if not tools:
        raise TasksError("the tool list has no usable tools")
    tasks = []
    for tool in tools:
        name = tool["name"]
        text, error, _ = call_with_retry(runner, bench_prompts.tasks_prompt(tools, name, per_tool))
        if error is not None:
            log(f"tool {_clip(repr(name))}: the model call failed ({_clip(error)}); no tasks for it")
            continue
        requests = bench_prompts.parse_task_list(text)
        if requests is None:
            log(f"tool {_clip(repr(name))}: the reply had no list of requests; no tasks for it")
            continue
        kept = []
        for request in requests:
            if request not in kept and not bench_prompts.mentions_name(request, name):
                kept.append(request)
        if not kept:
            log(f"tool {_clip(repr(name))}: no usable requests (empty, repeated, or naming the tool)")
        for request in kept[:per_tool]:
            tasks.append({"id": f"t{len(tasks) + 1:03d}", "request": request, "expected": name})
    if not tasks:
        raise TasksError("no tasks could be generated")
    info = {"toolsFingerprint": tools_fingerprint(tools)}
    if source and source.get("kind") == "stdio":
        info = {
            "serverName": source.get("serverName"),
            "serverVersion": source.get("serverVersion"),
            **info,
        }
    return {"tasksVersion": TASKS_VERSION, "source": info, "tasks": tasks}


# --- the patched view --------------------------------------------------------------------------
def patched_view(original, patch):
    """(patched tools, rename map, warnings): the tool list as `wrap` would serve it."""
    warnings = []
    router = Router(patch, False, warnings.append)
    router.client_line(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n')
    try:
        raw = (json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": original}}) + "\n").encode("ascii")
        out = router.server_line(raw)
        patched = json.loads(out.decode("utf-8"))["result"]["tools"]
    except (RecursionError, ValueError):
        raise BenchError("a tool is nested too deeply to benchmark") from None
    return patched, dict(router.rename_back), warnings


def _patch_info(original, patch):
    by_name = {t["name"]: t for t in original}
    stale = missing = 0
    for name, entry in patch["tools"].items():
        tool = by_name.get(name)
        if tool is None:
            missing += 1
        elif entry.get("base") is not None and entry["base"] != patch_format.fingerprint(tool):
            stale += 1
    entries = len(patch["tools"])
    return {"entries": entries, "applied": entries - stale - missing, "stale": stale, "missing": missing}


# --- estimates ---------------------------------------------------------------------------------
def estimate_calls(data, repeats):
    return len(data["tasks"]) * repeats * 2


def estimate_input_tokens(data, tools, patch, repeats):
    original = valid_tools(tools)
    patched, _, _ = patched_view(original, patch)
    total = 0
    for task in data["tasks"]:
        for listing in (original, patched):
            total += math.ceil(len(bench_prompts.trial_prompt(listing, task["request"])) / 4)
    return total * repeats


# --- trials ------------------------------------------------------------------------------------
def _order(count, seed, task_id, repeat):
    rng = random.Random(f"{seed}:{task_id}:{repeat}")
    order = list(range(count))
    rng.shuffle(order)
    return order


def _accuracy(outcomes):
    scored = [o for o in outcomes if o != "errored"]
    return None if not scored else sum(1 for o in scored if o == "correct") / len(scored)


def _side_summary(per_task):
    counts = {"correct": 0, "wrong": 0, "invalid": 0, "errored": 0}
    for outcomes in per_task.values():
        for outcome in outcomes:
            counts[outcome] += 1
    scored = counts["correct"] + counts["wrong"] + counts["invalid"]
    low, high = bench_stats.wilson(counts["correct"], scored)
    return {
        **counts,
        "accuracy": counts["correct"] / scored if scored else None,
        "interval": [low, high],
        "invalidRate": counts["invalid"] / scored if scored else None,
    }


def run_bench(tasks_data, tools, patch, runner, repeats=3, seed=0, tolerance=0.05):
    original = valid_tools(tools)
    patched, rename_back, patch_warnings = patched_view(original, patch)
    tasks = tasks_data["tasks"]
    per_task = {"original": {}, "patched": {}}
    calls = 0
    for task in tasks:
        for repeat in range(repeats):
            order = _order(len(original), seed, task["id"], repeat)
            for side, listing in (("original", original), ("patched", patched)):
                shown = [listing[i] for i in order]
                names = {t["name"] for t in shown}
                text, error, attempts = call_with_retry(
                    runner, bench_prompts.trial_prompt(shown, task["request"])
                )
                calls += attempts
                if error is not None:
                    outcome = "errored"
                else:
                    choice = bench_prompts.parse_choice(text, names)
                    if choice is None:
                        outcome = "invalid"
                    else:
                        if side == "patched":
                            choice = rename_back.get(choice, choice)
                        outcome = "correct" if choice == task["expected"] else "wrong"
                per_task[side].setdefault(task["id"], []).append(outcome)
    diffs = []
    for task in tasks:
        a_original = _accuracy(per_task["original"][task["id"]])
        a_patched = _accuracy(per_task["patched"][task["id"]])
        if a_original is not None and a_patched is not None:
            diffs.append(a_patched - a_original)
    mean, low, high = bench_stats.paired_bootstrap(diffs, seed)
    original_summary = _side_summary(per_task["original"])
    patched_summary = _side_summary(per_task["patched"])
    notes = [_clip(text) for text in patch_warnings]
    errored = original_summary["errored"] + patched_summary["errored"]
    if errored:
        notes.append(f"{errored} trials errored (the model call failed twice) and were excluded from accuracy")
    if len(diffs) < len(tasks):
        notes.append(f"{len(tasks) - len(diffs)} tasks had no scored repeat on one side and were dropped")
    return {
        "schemaVersion": 1,
        "runner": _clip(runner.describe()),
        "seed": seed,
        "repeats": repeats,
        "tolerance": tolerance,
        "tasks": len(tasks),
        "usableTasks": len(diffs),
        "droppedTasks": len(tasks) - len(diffs),
        "modelCalls": calls,
        "original": original_summary,
        "patched": patched_summary,
        "paired": {"mean": mean, "low": low, "high": high},
        "tokens": {
            "original": score_tools(original)["metrics"]["estimatedTokens"],
            "patched": score_tools(patched)["metrics"]["estimatedTokens"],
        },
        "patch": _patch_info(original, patch),
        "verdict": bench_stats.verdict(len(diffs), mean, low, high, tolerance),
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }


# --- rendering ---------------------------------------------------------------------------------
def render_bench_json(report):
    return json.dumps(report, indent=2, ensure_ascii=True) + "\n"


def _pct(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _row(label, side):
    low, high = side["interval"]
    return (
        f"{label:<10}{side['correct']:>8}{side['wrong']:>7}{side['invalid']:>9}{side['errored']:>9}"
        f"{_pct(side['accuracy']):>10}   [{_pct(low)}, {_pct(high)}]"
    )


def render_bench_text(report):
    verdict = report["verdict"]
    paired = report["paired"]
    tokens = report["tokens"]
    patch = report["patch"]
    lines = [
        f"mcp-fixer bench: {verdict['verdict']}",
        f"runner: {_clip(report['runner'])}, seed {report['seed']}, {report['repeats']} repeats, "
        f"tolerance {report['tolerance']}",
        f"tasks: {report['usableTasks']} usable of {report['tasks']} ({report['droppedTasks']} dropped); "
        f"model calls {report['modelCalls']}",
        "",
        f"{'':<10}{'correct':>8}{'wrong':>7}{'invalid':>9}{'errored':>9}{'accuracy':>10}   95% interval",
        _row("original", report["original"]),
        _row("patched", report["patched"]),
        "",
        f"paired difference (patched - original): {paired['mean'] * 100:+.1f} points, "
        f"95% interval [{paired['low'] * 100:+.1f}, {paired['high'] * 100:+.1f}]",
        f"tokens: original {tokens['original']} -> patched {tokens['patched']} "
        f"({tokens['patched'] - tokens['original']:+d})",
        f"patch: {patch['entries']} entries, {patch['applied']} applied, "
        f"{patch['stale']} stale, {patch['missing']} missing",
        "",
        f"verdict: {verdict['verdict']} - {_clip(verdict['reason'])}",
    ]
    for note in report["notes"]:
        lines.append(f"note: {_clip(note)}")
    lines += ["", report["disclaimer"]]
    return "\n".join(lines) + "\n"
