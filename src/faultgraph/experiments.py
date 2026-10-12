"""Immutable, family-split diagnostic studies with exact checks and raw data."""

import json
import os
import platform
import random
import resource
import signal
import statistics
import sys
import tracemalloc
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from math import fsum, prod
from pathlib import Path
from time import perf_counter

from .bdd import BDD
from .construct import graph_for_predicate, model_for_domain, threshold_expr
from .evaluator import operational
from .expr import Not, Var
from .metrics import model_metrics
from .model import ConditionedModel, load_json, save_model, states
from .optimize import optimize, pareto
from .oracle import domain_truth
from .paper import write_csv
from .reliability import monte_carlo
from .transform import combine_wedge


@contextmanager
def deadline(seconds):
    old = signal.getsignal(signal.SIGALRM)

    def timeout(*_):
        raise TimeoutError("predeclared per-model budget exceeded")

    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def timing(indicator, samples, repeats):
    for s in samples[:10]:
        indicator(s)
    elapsed = []
    for _ in range(repeats):
        for s in samples:
            start = perf_counter()
            indicator(s)
            elapsed.append((perf_counter() - start) * 1000)
    elapsed.sort()
    # Allocation run separate from timing (tracemalloc overhead excluded).
    tracemalloc.start()
    for s in samples:
        indicator(s)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "evaluation_p50_ms": statistics.median(elapsed),
        "evaluation_p95_ms": elapsed[min(len(elapsed) - 1, int(0.95 * len(elapsed)))],
        "peak_python_allocation_bytes": peak,
        "timed_evaluations": len(elapsed),
        "raw_timings_ms": elapsed,
    }


def weighted(table, ps):
    value = fsum(
        prod(p if x else 1 - p for x, p in zip(s, ps, strict=False)) for s, v in table if v
    )
    return min(1.0, max(0.0, value))


def run_study(manifest_path, out):
    manifest_path, out = Path(manifest_path), Path(out)
    if out.exists():
        raise ValueError("immutable study output already exists; choose a new output path")
    manifest = load_json(manifest_path)
    dataset = manifest_path.parent / manifest["dataset"]
    if sha256(dataset.read_bytes()).hexdigest() != manifest["dataset_sha256"]:
        raise ValueError("frozen dataset hash mismatch")
    cases = load_json(dataset)
    if set(manifest["heldout_families"]) & set(manifest["development_families"]):
        raise ValueError("family split leakage")
    if {c["kind"] for c in cases} != set(
        manifest["heldout_families"] + manifest["development_families"]
    ):
        raise ValueError("unclassified dataset family")
    out.mkdir(parents=True)
    (out / "models").mkdir()
    source_hashes = {
        p.name: sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    system = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "started_at": datetime.now(UTC).isoformat(),
        "source_sha256": source_hashes,
        "timing": "single-process CPython; warmup 10; per-call wall clock; identical uniform states across arms",
        "memory": "tracemalloc per-arm evaluation peak; RSS is cumulative process-wide only",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    result_rows, raw_rows, failures, reliability_rows, certificates = [], [], [], [], []
    total_states, model_hashes = 0, {}
    start_study = perf_counter()
    for _index, spec in enumerate(cases):
        case = f"{spec['kind']}-n{spec['n']}-s{spec['seed']}"
        start = perf_counter()
        try:
            with deadline(manifest["per_model_timeout_seconds"]):
                n = spec["n"]
                domain = list(states(n))
                truth = [(s, domain_truth(spec, s)) for s in domain]
                build_start = perf_counter()
                baseline = model_for_domain(spec)
                construction_ms = (perf_counter() - build_start) * 1000
                models = {"B_gl": baseline}
                build_times = {"B_gl": construction_ms}
                if spec["kind"] == "conditional":
                    naive_start = perf_counter()
                    a = graph_for_predicate(n, threshold_expr(n, spec["high"]), "path", 3)
                    b = graph_for_predicate(n, threshold_expr(n, spec["low"]), "star", 4)
                    models["B_naive_HAIT"] = combine_wedge(
                        ConditionedModel((Var(1), Not(Var(1))), (a, b))
                    )
                    build_times["B_naive_HAIT"] = (perf_counter() - naive_start) * 1000
                for arm, topology, expressions in (
                    ("B_candidate", True, True),
                    ("A_topology", True, False),
                    ("A_expression", False, True),
                ):
                    candidate = optimize(
                        baseline,
                        manifest["optimizer_budget"],
                        topology=topology,
                        expressions=expressions,
                    )
                    models[arm] = candidate["model"]
                    build_times[arm] = candidate["elapsed_ms"]
                    certificates.append(
                        {
                            "case": case,
                            "arm": arm,
                            **{k: v for k, v in candidate.items() if k != "model"},
                        }
                    )
                rng = random.Random(5000 + spec["seed"] + n)
                samples = [
                    tuple(rng.randrange(2) for _ in range(n))
                    for _ in range(manifest["evaluation_samples"])
                ]
                observed = {}
                for arm, m in models.items():
                    model_hashes[case + ":" + arm] = m.digest
                    save_model(m, out / "models" / (case + "-" + arm + ".json"))
                    vals = [operational(m, s) for s in domain]
                    observed[arm] = list(zip(domain, vals, strict=False))
                    witnesses = [
                        "".join(map(str, s))
                        for (s, t), v in zip(truth, vals, strict=False)
                        if t != v
                    ]
                    metrics = model_metrics(m)
                    timed = timing(
                        lambda s, m=m: operational(m, s), samples, manifest["timing_repeats"]
                    )
                    raw_rows.append(
                        {
                            "case": case,
                            "arm": arm,
                            "states_sha256": sha256(json.dumps(samples).encode()).hexdigest(),
                            "raw_timings_ms": timed.pop("raw_timings_ms"),
                        }
                    )
                    result_rows.append(
                        {
                            "case": case,
                            "family": spec["kind"],
                            "split": "heldout"
                            if spec["kind"] in manifest["heldout_families"]
                            else "development",
                            "n": n,
                            "seed": spec["seed"],
                            "arm": arm,
                            "states": len(domain),
                            "mismatches": len(witnesses),
                            "exact_truth_accuracy": (len(domain) - len(witnesses)) / len(domain),
                            "vertices": metrics["vertices"],
                            "edges": metrics["edges"],
                            "expression_ops": metrics["total"],
                            "dag_nodes": metrics["dag_nodes"],
                            "serialized_model_size_kB": metrics["serialized_bytes"] / 1024,
                            "construction_time_ms": build_times[arm],
                            **timed,
                        }
                    )
                    if witnesses:
                        failures.append(
                            {
                                "case": case,
                                "arm": arm,
                                "status": "COUNTEREXAMPLE",
                                "witnesses": witnesses,
                            }
                        )
                bdd_start = perf_counter()
                bdd = BDD.from_indicator(n, lambda s, baseline=baseline: operational(baseline, s))
                bdd_build_ms = (perf_counter() - bdd_start) * 1000
                for s, t in truth:
                    if bdd.evaluate(s) != t:
                        failures.append(
                            {
                                "case": case,
                                "arm": "B_canonical",
                                "status": "COUNTEREXAMPLE",
                                "witness": "".join(map(str, s)),
                            }
                        )
                        break
                raw_rows.append(
                    {
                        "case": case,
                        "arm": "B_canonical",
                        "bdd_nodes": len(bdd.nodes) - 2,
                        "construction_time_ms": bdd_build_ms,
                        **timing(bdd.evaluate, samples, manifest["timing_repeats"]),
                    }
                )
                raw_rows.append(
                    {
                        "case": case,
                        "arm": "B_truth",
                        **timing(
                            lambda s, spec=spec: domain_truth(spec, s),
                            samples,
                            manifest["timing_repeats"],
                        ),
                    }
                )
                for p in manifest["working_probability_grid"]:
                    ps = [p] * n
                    ref = weighted(truth, ps)
                    gl = weighted(observed["B_gl"], ps)
                    bdd_r = bdd.reliability(ps)
                    # Each generator seed supplies one diagnostic MC repeat at each p.
                    mc = monte_carlo(
                        n,
                        lambda s, spec=spec: domain_truth(spec, s),
                        ps,
                        manifest["mc_samples"],
                        spec["seed"],
                    )
                    reliability_rows.append(
                        {
                            "case": case,
                            "family": spec["kind"],
                            "p": p,
                            "law": "independent",
                            "oracle_exact": ref,
                            "gl_exact": gl,
                            "bdd_exact": bdd_r,
                            "exact_error": abs(gl - ref),
                            "bdd_error": abs(bdd_r - ref),
                            **mc.to_dict(),
                            "absolute_error": abs(mc.estimate - ref),
                            "covered": mc.lower <= ref <= mc.upper,
                        }
                    )
                    if abs(gl - ref) > 1e-12 or abs(bdd_r - ref) > 1e-12:
                        failures.append(
                            {"case": case, "status": "RELIABILITY_DISAGREEMENT", "p": p}
                        )
                ps = [0.7 + 0.25 * (i / (n - 1)) for i in range(n)]
                ref = weighted(truth, ps)
                gl = weighted(observed["B_gl"], ps)
                raw_rows.append(
                    {
                        "case": case,
                        "law": "nonidentical-independent",
                        "probabilities": ps,
                        "oracle_exact": ref,
                        "gl_exact": gl,
                    }
                )
                if abs(gl - ref) > 1e-12:
                    failures.append(
                        {"case": case, "status": "NONIDENTICAL_RELIABILITY_DISAGREEMENT"}
                    )
                q = manifest["common_cause_q"]
                ps = [0.9] * n
                ref = q * domain_truth(spec, (0,) * n) + (1 - q) * weighted(truth, ps)
                mc = monte_carlo(
                    n,
                    lambda s, spec=spec: domain_truth(spec, s),
                    ps,
                    manifest["mc_samples"],
                    spec["seed"],
                    q,
                )
                correlated_gl = q * operational(baseline, (0,) * n) + (1 - q) * weighted(
                    observed["B_gl"], ps
                )
                reliability_rows.append(
                    {
                        "case": case,
                        "family": spec["kind"],
                        "p": 0.9,
                        "law": "common-cause q=0.1",
                        "oracle_exact": ref,
                        "gl_exact": correlated_gl,
                        "bdd_exact": q * bdd.evaluate((0,) * n) + (1 - q) * bdd.reliability(ps),
                        "exact_error": abs(correlated_gl - ref),
                        "bdd_error": abs(
                            q * bdd.evaluate((0,) * n) + (1 - q) * bdd.reliability(ps) - ref
                        ),
                        **mc.to_dict(),
                        "absolute_error": abs(mc.estimate - ref),
                        "covered": mc.lower <= ref <= mc.upper,
                    }
                )
                raw_rows.append(
                    {
                        "case": case,
                        "pareto_structural": pareto(models),
                        "elapsed_ms": (perf_counter() - start) * 1000,
                    }
                )
                total_states += len(domain)
        except Exception as e:  # noqa: BLE001 — preserve failed research cases and continue
            if tracemalloc.is_tracing():
                tracemalloc.stop()
            failures.append(
                {
                    "case": case,
                    "status": "TIMEOUT" if isinstance(e, TimeoutError) else "ERROR",
                    "message": str(e),
                }
            )
        # Keep partial traces even if the run is interrupted.
        for filename, rows in (("raw_runs.jsonl", raw_rows), ("failed_runs.jsonl", failures)):
            (out / filename).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    if result_rows:
        write_csv(out / "results.csv", result_rows)
    if reliability_rows:
        write_csv(out / "reliability.csv", reliability_rows)
    (out / "certificates.json").write_text(json.dumps(certificates, indent=2) + "\n")
    (out / "model_hashes.json").write_text(
        json.dumps(model_hashes, indent=2, sort_keys=True) + "\n"
    )
    system["elapsed_seconds"] = perf_counter() - start_study
    system["process_peak_RSS_MB"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024**2 if sys.platform == "darwin" else 1024
    )
    (out / "system_info.json").write_text(json.dumps(system, indent=2) + "\n")
    ci = {
        family: {
            "diagnostic_intervals": len(rows),
            "covered": sum(r["covered"] for r in rows),
            "coverage_fraction": sum(r["covered"] for r in rows) / len(rows),
            "mean_absolute_error": statistics.mean(r["absolute_error"] for r in rows),
            "interpretation": "marginal diagnostic Wilson coverage across dependent design cases; no family-general inference",
        }
        for family in {r["family"] for r in reliability_rows}
        if (rows := [r for r in reliability_rows if r["family"] == family])
    }
    (out / "confidence_intervals.json").write_text(json.dumps(ci, indent=2, sort_keys=True) + "\n")
    summary = {
        "model_count": len(cases),
        "completed_models": len({r["case"] for r in result_rows}),
        "family_count": len({c["kind"] for c in cases}),
        "domain_states": total_states,
        "arm_state_comparisons": sum(r["states"] for r in result_rows),
        "failure_count": len(failures),
        "mismatches": sum(r["mismatches"] for r in result_rows),
        "elapsed_seconds": system["elapsed_seconds"],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    report(out)
    return summary


def report(study):
    import csv

    study = Path(study)
    summary = load_json(study / "summary.json")
    manifest = load_json(study / "manifest.json")
    split_note = (
        "Candidate implementation frozen before supplemental dataset generation; no retuning."
        if manifest["study_id"] == "native-validation"
        else "Frozen complete-family holdout established before candidate implementation. No tuning on heldout."
    )
    rows = list(csv.DictReader((study / "results.csv").open()))
    text = [
        "# Diagnostic study results",
        "",
        json.dumps(summary, indent=2),
        "",
        "Generated synthetic domains, not field deployments. Exact finite state checks are not universal proofs.",
        split_note,
        "Pilot repeats only; no statistical superiority or novelty claim. Runtime regressions are retained.",
        "",
        "| Family | Models | V improved | E improved | Ops improved | p50 faster | p50 slower |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family in sorted({r["family"] for r in rows}):
        base = {r["case"]: r for r in rows if r["family"] == family and r["arm"] == "B_gl"}
        candidate = {
            r["case"]: r for r in rows if r["family"] == family and r["arm"] == "B_candidate"
        }
        counts = [
            sum(float(candidate[c][key]) < float(base[c][key]) for c in candidate)
            for key in ("vertices", "edges", "expression_ops", "evaluation_p50_ms")
        ]
        slower = sum(
            float(candidate[c]["evaluation_p50_ms"]) > float(base[c]["evaluation_p50_ms"])
            for c in candidate
        )
        text.append(
            f"| {family} | {len(candidate)} | " + " | ".join(map(str, counts)) + f" | {slower} |"
        )
    text.extend(
        [
            "",
            "Memory: per-arm tracemalloc allocation peaks; process-wide peak RSS is separately recorded.",
            "BDD construction explicitly enumerates 2^n states; its fast evaluation has a preprocessing cost.",
            "Structural Pareto frontier uses V,E,tree-ops only; runtime is measured separately.",
            "F06 inter-subsystem full construction, PRISM/Storm, SMT and dynamic service mapping are not compared.",
        ]
    )
    (study / "study_summary.md").write_text("\n".join(text) + "\n")
    return {"report": str(study / "study_summary.md"), **summary}
