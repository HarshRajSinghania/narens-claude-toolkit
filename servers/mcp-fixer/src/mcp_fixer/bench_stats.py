"""Statistics and the verdict for the benchmark. Pure; standard library only."""
import math
import random

Z = 1.959963984540054  # 95% two-sided
MIN_TASKS = 30


def wilson(correct, total):
    """The 95% Wilson score interval for `correct` out of `total`; (0, 1) when there is no data."""
    if total <= 0:
        return (0.0, 1.0)
    p = correct / total
    denominator = 1 + Z * Z / total
    centre = (p + Z * Z / (2 * total)) / denominator
    half = Z * math.sqrt(p * (1 - p) / total + Z * Z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def paired_bootstrap(diffs, seed=0, resamples=2000):
    """(mean, low, high): the mean of `diffs` and a 95% percentile interval from a seeded bootstrap."""
    n = len(diffs)
    if n == 0:
        return (0.0, -1.0, 1.0)
    mean = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(
        sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)
    )
    low_index = int(0.025 * resamples)
    high_index = max(low_index, int(0.975 * resamples) - 1)
    return (mean, means[low_index], means[high_index])


def tasks_needed(n, mean, low, high, tolerance):
    """About how many tasks it would take for the interval's lower bound to clear the tolerance.

    None when the observed difference is itself at or beyond the tolerance (more tasks would not
    help) or the interval has no width to scale.
    """
    margin = mean + tolerance
    half = (high - low) / 2
    if margin <= 0 or half <= 0:
        return None
    return max(math.ceil(n * (half / margin) ** 2), n + 1)


def verdict(n, mean, low, high, tolerance, min_tasks=MIN_TASKS):
    """{"verdict", "reason", "tasksNeeded"} for a paired comparison over `n` tasks."""
    if n > 0 and high < 0:
        return {
            "verdict": "worse",
            "reason": "the patched list picked the right tool less often: the whole interval is below zero",
            "tasksNeeded": None,
        }
    if n >= min_tasks and low > -tolerance:
        return {
            "verdict": "no drop detected",
            "reason": f"the interval's lower bound ({low:+.3f}) is within the {tolerance} tolerance",
            "tasksNeeded": None,
        }
    if n < min_tasks:
        return {
            "verdict": "inconclusive",
            "reason": f"only {n} usable tasks; at least {min_tasks} are needed (add at least {min_tasks - n} more)",
            "tasksNeeded": None,
        }
    needed = tasks_needed(n, mean, low, high, tolerance)
    if needed is None:
        reason = (
            f"the observed difference ({mean:+.3f}) is already at or beyond the {tolerance} tolerance, "
            "and more tasks would not change that"
        )
    else:
        reason = (
            f"the interval ({low:+.3f} to {high:+.3f}) is too wide to rule out a drop of {tolerance}; "
            f"about {needed} tasks would be needed at this spread"
        )
    return {"verdict": "inconclusive", "reason": reason, "tasksNeeded": needed}
