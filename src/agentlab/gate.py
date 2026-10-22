"""Release decision: PASS / BLOCK / INSUFFICIENT_EVIDENCE. Critical failures can't be averaged away, and missing
evidence (errors, unsupported critical checks, uncovered scenarios) never turns into a pass."""

import math
from statistics import median


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p, d = k / n, 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def p95(xs: list[float]) -> float | None:
    return sorted(xs)[min(len(xs) - 1, math.ceil(0.95 * len(xs)) - 1)] if xs else None


def summarize(trials: list[dict]) -> dict:
    graded = [t for t in trials if t["status"] in ("passed", "failed")]
    k, n = sum(t["status"] == "passed" for t in graded), len(graded)
    lat = [t["record"]["latency_ms"] for t in graded]
    return {"passed": k, "graded": n, "errors": len(trials) - n, "pass_rate": k / n if n else None,
            "ci95": wilson(k, n), "p50_ms": median(lat) if lat else None, "p95_ms": p95(lat)}


def decide(trials: list[dict], scenarios: list[str], candidate: str, baseline: str | None = None,
           max_regression: float = 0.0) -> dict:
    cand = [t for t in trials if t["target"] == candidate]
    block, insufficient, gaps = [], [], set()

    if errors := [t for t in cand if t["status"] not in ("passed", "failed")]:
        codes = sorted({t["record"].get("error", {}).get("code", "INCOMPLETE") for t in errors})
        insufficient.append(f"{len(errors)} trial(s) did not complete ({', '.join(codes)}); excluded from rates")
    for s in scenarios:
        if not any(t["scenario"] == s and t["status"] in ("passed", "failed") for t in cand):
            insufficient.append(f"no graded trial for {s}")

    for t in cand:
        for a in t["record"].get("assertions", []):
            where = f"{t['scenario']}: {a['description']}"
            if a["critical"] and a["status"] == "fail":
                block.append(f"critical check failed: {where}")
            elif a["critical"] and a["status"] == "unsupported":
                insufficient.append(f"critical check unsupported by harness: {where}")
            elif a["status"] == "unsupported":
                gaps.add(f"{t['scenario']}: {a['description']} ({a['detail']})")

    stats = {candidate: summarize(cand)}
    paired = None
    if baseline:
        base = [t for t in trials if t["target"] == baseline]
        stats[baseline] = summarize(base)
        outcome = {(t["scenario"], t["repeat"]): t["status"] for t in base}
        pairs = [(outcome[(t["scenario"], t["repeat"])], t["status"]) for t in cand
                 if t["status"] in ("passed", "failed") and outcome.get((t["scenario"], t["repeat"])) in ("passed", "failed")]
        paired = {"pairs": len(pairs), "regressions": pairs.count(("passed", "failed")), "fixes": pairs.count(("failed", "passed"))}
        b, c = stats[baseline]["pass_rate"], stats[candidate]["pass_rate"]
        if b is not None and c is not None and paired["regressions"] and c < b - max_regression:
            block.append(f"pass rate regressed {b:.0%} -> {c:.0%} ({paired['regressions']} paired regression(s))")

    status = "BLOCK" if block else "INSUFFICIENT_EVIDENCE" if insufficient else "PASS"
    # Dedupe while keeping order: repeats of the same failing check add noise, not information.
    return {"status": status, "candidate": candidate, "baseline": baseline, "block_reasons": list(dict.fromkeys(block)),
            "insufficient_reasons": list(dict.fromkeys(insufficient)), "coverage_gaps": sorted(gaps),
            "stats": stats, "paired": paired}
