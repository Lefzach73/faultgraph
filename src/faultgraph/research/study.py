"""Prospective sequential, process-isolated research measurement and reporting."""

import json
import math
import os
import platform
import random
import resource
import signal
import statistics
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from itertools import product
from pathlib import Path
from time import perf_counter, perf_counter_ns

from ..bdd import BDD
from ..evaluator import operational
from ..metrics import model_metrics
from ..optimize import optimize
from ..paper import write_csv
from .domains import domain_oracle, naive, published
from .guarded import prune_edges, search
from .kernel import Program

ARMS = (
    "published",
    "naive",
    "local",
    "semantic-prune",
    "greedy-global",
    "greedy-cut",
    "beam-cut",
    "bdd",
)


@contextmanager
def deadline(seconds):
    old = signal.getsignal(signal.SIGALRM)

    def stop(*_):
        raise TimeoutError("predeclared phase deadline exceeded")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def measure(indicator, samples, repeats):
    for state in samples[:16]:
        indicator(state)
    times = []
    for _ in range(repeats):
        for state in samples:
            start = perf_counter_ns()
            indicator(state)
            times.append(perf_counter_ns() - start)
    ordered = sorted(times)
    return {
        "p50_ms": statistics.median(ordered) / 1e6,
        "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1] / 1e6,
        "raw_ns": times,
    }


def weight(table, p):
    n = len(table[0][0])
    return min(
        1.0,
        max(0.0, math.fsum(p ** sum(s) * (1 - p) ** (n - sum(s)) for s, value in table if value)),
    )


def worker(spec, manifest, arm):
    started = perf_counter()
    model = None
    algorithm = {}
    bdd = None
    construction_status = "COMPLETE"
    base = published(spec)
    base_build = (perf_counter() - started) * 1000
    with deadline(max(0.001, manifest["construction_seconds"] - (perf_counter() - started))):
        if arm == "published":
            model = base
        elif arm == "naive":
            model = naive(spec)
        elif arm == "local":
            algorithm = optimize(base, manifest["budget_proposals"])
            model = algorithm["model"]
        elif arm == "semantic-prune":
            algorithm = prune_edges(
                base, manifest["budget_proposals"], manifest["construction_seconds"]
            )
            model = algorithm["model"]
        elif arm in ("greedy-global", "greedy-cut", "beam-cut"):
            algorithm = search(
                base,
                strategy=arm,
                budget=manifest["budget_proposals"],
                beam_width=manifest["beam_width"],
                seconds=manifest["construction_seconds"],
            )
            model = algorithm["model"]
        elif arm == "bdd":
            bdd = BDD.from_indicator(spec["n"], lambda s: operational(base, s))
        else:
            raise ValueError("unknown comparator")
        program = Program.build(model) if model else None
    construction_ms = (perf_counter() - started) * 1000
    if algorithm.get("status") == "TIMEOUT":
        construction_status = "TIMEOUT_WITH_CERTIFIED_INCUMBENT"
    states = list(product((0, 1), repeat=spec["n"]))
    truth = []
    actual = []
    mismatches = []
    check_start = perf_counter()
    with deadline(manifest["verification_seconds"]):
        for state in states:
            expected = domain_oracle(spec, state)
            result = bdd.evaluate(state) if bdd else operational(model, state)
            compiled = result if bdd else program.evaluate(state)
            truth.append(expected)
            actual.append(result)
            if expected != result or compiled != expected:
                mismatches.append(
                    {
                        "state": "".join(map(str, state)),
                        "oracle": expected,
                        "scalar": result,
                        "compiled": compiled,
                    }
                )
    verification_ms = (perf_counter() - check_start) * 1000
    rng = random.Random(310000 + spec["seed"] + spec["n"])
    samples = [
        tuple(rng.randrange(2) for _ in range(spec["n"])) for _ in range(manifest["samples"])
    ]
    if bdd:
        scalar = dag = measure(bdd.evaluate, samples, manifest["repeats"])
        metrics = {
            "vertices": None,
            "edges": None,
            "and": None,
            "or": None,
            "not": None,
            "total": None,
            "dag_ops": None,
            "bdd_nodes": len(bdd.nodes) - 2,
            "serialized_bytes": len(json.dumps(bdd.nodes).encode()),
        }
    else:
        scalar = measure(lambda s: operational(model, s), samples, manifest["repeats"])
        dag = measure(program.evaluate, samples, manifest["repeats"])
        metrics = {**model_metrics(model), "dag_ops": program.dag_ops, "bdd_nodes": None}
    table = list(zip(states, actual, strict=True))
    oracle_table = list(zip(states, truth, strict=True))
    reliability = []
    for p in manifest["working_p"]:
        ref = weight(oracle_table, p)
        r = weight(table, p)
        reliability.append(
            {
                "p": p,
                "law": "independent",
                "oracle": ref,
                "model": r,
                "absolute_error": abs(ref - r),
                "bdd_recursive": bdd.reliability([p] * spec["n"]) if bdd else None,
            }
        )
    q = manifest["common_cause_q"]
    p = 0.9
    ref = q * truth[0] + (1 - q) * weight(oracle_table, p)
    r = q * actual[0] + (1 - q) * weight(table, p)
    reliability.append(
        {
            "p": p,
            "law": "common-cause",
            "q": q,
            "oracle": ref,
            "model": r,
            "absolute_error": abs(ref - r),
            "incorrect_independence_control": weight(oracle_table, (1 - q) * p),
        }
    )
    if bdd:
        witness_model = {"n": bdd.n, "root": bdd.root, "nodes": bdd.nodes}
    else:
        witness_model = model.to_dict()
    record = {
        "case": spec["id"],
        "family": spec["family"],
        "n": spec["n"],
        "seed": spec["seed"],
        "arm": arm,
        "status": "COUNTEREXAMPLE" if mismatches else construction_status,
        "checked_states": len(states),
        "mismatches": mismatches,
        "metrics": metrics,
        "construction_ms": construction_ms,
        "base_build_ms": base_build,
        "verification_ms": verification_ms,
        "scalar": scalar,
        "dag": dag,
        "reliability": reliability,
        "peak_RSS_MB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / (1024**2 if sys.platform == "darwin" else 1024),
        "truth_sha256": sha256(bytes(actual)).hexdigest(),
        "model": witness_model,
        "model_hash": model.digest
        if model
        else sha256(json.dumps(witness_model, sort_keys=True).encode()).hexdigest(),
        "algorithm": {k: v for k, v in algorithm.items() if k not in ("model", "frontier")},
        "frontier": [m.to_dict() for m in algorithm.get("frontier", [])],
        "sample_hash": sha256(json.dumps(samples).encode()).hexdigest(),
        "influential_processors": [
            i + 1
            for i in range(spec["n"])
            if any(truth[j] != truth[j ^ (1 << (spec["n"] - i - 1))] for j in range(len(truth)))
        ],
    }
    return record


def run(manifest_path, out):
    path = Path(manifest_path)
    manifest = json.loads(path.read_text())
    out = Path(out)
    if out.exists():
        raise ValueError("immutable output already exists; choose a new study directory")
    data = path.parent / "cases.json"
    if sha256(data.read_bytes()).hexdigest() != manifest["dataset_sha256"]:
        raise ValueError("frozen data changed")
    cases = json.loads(data.read_text())
    out.mkdir(parents=True)
    (out / "models").mkdir()
    (out / "lineage").mkdir()
    (out / "manifest.json").write_bytes(path.read_bytes())
    (out / "cases.json").write_bytes(data.read_bytes())
    system = {
        "python": sys.version,
        "compiler": platform.python_compiler(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "started_at": datetime.now(UTC).isoformat(),
        "cpu": subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if sys.platform == "darwin"
        else platform.processor(),
        "source_hashes": {
            str(p): sha256(p.read_bytes()).hexdigest()
            for p in Path("src/faultgraph/research").glob("*.py")
        },
        "measurement": "fresh sequential process per case/arm; construction+verification+evaluation peak RSS; no parallel benchmark workers",
    }
    (out / "system_info.json").write_text(json.dumps(system, indent=2) + "\n")
    rows = []
    failures = []
    wall = perf_counter()
    for case_index, spec in enumerate(cases):
        order = list(ARMS)
        shift = (spec["seed"] + spec["n"]) % len(order)
        order = order[shift:] + order[:shift]
        for arm in order:
            command = [
                sys.executable,
                "-m",
                "faultgraph.research",
                "worker",
                "--manifest",
                str(path),
                "--case",
                str(case_index),
                "--arm",
                arm,
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=manifest["construction_seconds"]
                    + manifest["verification_seconds"]
                    + 60,
                )
                if result.returncode:
                    raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:])
                record = json.loads(result.stdout)
            except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as error:
                record = {
                    "case": spec["id"],
                    "family": spec["family"],
                    "n": spec["n"],
                    "seed": spec["seed"],
                    "arm": arm,
                    "status": "TIMEOUT"
                    if isinstance(error, subprocess.TimeoutExpired)
                    else "ERROR",
                    "error": str(error),
                }
            with (out / "raw_runs.jsonl").open("a") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
            if record["status"] != "COMPLETE":
                failures.append(
                    {
                        k: v
                        for k, v in record.items()
                        if k not in ("model", "frontier", "scalar", "dag", "algorithm")
                    }
                )
            if "metrics" in record:
                tag = spec["id"] + "-" + arm
                (out / "models" / (tag + ".json")).write_text(
                    json.dumps(record["model"], indent=2) + "\n"
                )
                (out / "lineage" / (tag + ".json")).write_text(
                    json.dumps(
                        {"algorithm": record["algorithm"], "frontier": record["frontier"]}, indent=2
                    )
                    + "\n"
                )
                m = record["metrics"]
                rows.append(
                    {
                        "case": spec["id"],
                        "family": spec["family"],
                        "n": spec["n"],
                        "seed": spec["seed"],
                        "arm": arm,
                        "status": record["status"],
                        "checked_states": record["checked_states"],
                        "mismatch_count": len(record["mismatches"]),
                        **{
                            k: m[k]
                            for k in (
                                "vertices",
                                "edges",
                                "and",
                                "or",
                                "not",
                                "total",
                                "dag_ops",
                                "bdd_nodes",
                                "serialized_bytes",
                            )
                        },
                        "construction_ms": record["construction_ms"],
                        "verification_ms": record["verification_ms"],
                        "peak_RSS_MB": record["peak_RSS_MB"],
                        "scalar_p50_ms": record["scalar"]["p50_ms"],
                        "scalar_p95_ms": record["scalar"]["p95_ms"],
                        "dag_p50_ms": record["dag"]["p50_ms"],
                        "dag_p95_ms": record["dag"]["p95_ms"],
                        "model_hash": record["model_hash"],
                        "truth_sha256": record["truth_sha256"],
                    }
                )
            with (out / "progress.json").open("w") as f:
                json.dump(
                    {
                        "case": case_index + 1,
                        "arm": arm,
                        "completed_rows": len(rows),
                        "failures": len(failures),
                    },
                    f,
                )
        print(
            json.dumps(
                {
                    "case": case_index + 1,
                    "total": len(cases),
                    "id": spec["id"],
                    "failures": len(failures),
                }
            ),
            flush=True,
        )
    if rows:
        write_csv(out / "results.csv", rows)
    else:
        (out / "results.csv").write_text("case,family,arm,status,mismatch_count\n")
    (out / "failed_runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in failures))
    summary = {
        "status": "COMPLETE" if not failures else "COMPLETED_WITH_FAILURES",
        "cases": len(cases),
        "families": len(manifest["families"]),
        "arms": list(ARMS),
        "arm_runs": len(rows),
        "failures": len(failures),
        "mismatches": sum(r["mismatch_count"] for r in rows),
        "arm_state_comparisons": sum(r["checked_states"] for r in rows),
        "seconds": perf_counter() - wall,
        "scope": "finite n<=12; cases/assignments are not independent system families",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    analyze(out)
    return summary


def analyze(out):
    import csv

    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text())
    with (out / "results.csv").open() as f:
        rows = list(csv.DictReader(f))
    grouped = {}
    for row in rows:
        grouped.setdefault(row["case"], {})[row["arm"]] = row
    family_rows = []
    paired = []
    for family in manifest["families"]:
        ratios = []
        for case, arms in grouped.items():
            if next(iter(arms.values()))["family"] != family:
                continue
            if not {"local", "greedy-global", "beam-cut", "greedy-cut"} <= arms.keys():
                continue
            c, local, g, a = (arms[k] for k in ("beam-cut", "local", "greedy-global", "greedy-cut"))
            r = {
                "case": case,
                "family": family,
                "seed": int(c["seed"]),
                "p50_vs_local": float(c["dag_p50_ms"]) / float(local["dag_p50_ms"]),
                "p50_vs_global": float(c["dag_p50_ms"]) / float(g["dag_p50_ms"]),
                "dag_vs_local": float(c["dag_ops"]) / max(1, float(local["dag_ops"])),
                "construction_vs_local": float(c["construction_ms"])
                / max(0.000001, float(local["construction_ms"])),
                "rss_vs_local": float(c["peak_RSS_MB"]) / float(local["peak_RSS_MB"]),
                "vertices_delta": int(c["vertices"]) - int(local["vertices"]),
                "edges_delta": int(c["edges"]) - int(local["edges"]),
                "tree_delta": int(c["total"]) - int(local["total"]),
                "beam_greedy_equal": c["model_hash"] == a["model_hash"],
            }
            paired.append(r)
            ratios.append(r)
        # Cluster all n values for each generator seed, then aggregate seeds per family.
        clusters = [
            {
                k: statistics.median(r[k] for r in ratios if r["seed"] == seed)
                for k in (
                    "p50_vs_local",
                    "p50_vs_global",
                    "dag_vs_local",
                    "rss_vs_local",
                    "construction_vs_local",
                )
            }
            for seed in sorted({r["seed"] for r in ratios})
        ]
        med = {
            k: statistics.median(c[k] for c in clusters) if clusters else None
            for k in (
                "p50_vs_local",
                "p50_vs_global",
                "dag_vs_local",
                "rss_vs_local",
                "construction_vs_local",
            )
        }
        expected = len(
            [c for c in json.loads((out / "cases.json").read_text()) if c["family"] == family]
        )
        complete = (
            len(ratios) == expected
            and sum(r["family"] == family for r in rows) == expected * len(ARMS)
            and all(arms["status"] == "COMPLETE" for arms in rows if arms["family"] == family)
        )
        success = (
            complete
            and med["p50_vs_local"] <= 0.9
            and med["p50_vs_global"] <= 0.9
            and med["dag_vs_local"] <= 1.25
        )
        family_rows.append(
            {
                "family": family,
                "paired_cases": len(ratios),
                "complete": complete,
                **med,
                "H_guard_family_pass": success,
                "runtime_regressions_vs_local": sum(r["p50_vs_local"] > 1 for r in ratios),
                "smaller_graph_cases": sum(
                    r["vertices_delta"] < 0 or r["edges_delta"] < 0 for r in ratios
                ),
            }
        )
    if paired:
        write_csv(out / "paired_cases.csv", paired)
    write_csv(out / "family_results.csv", family_rows)
    rng = random.Random(manifest["bootstrap_seed"])
    bootstrap = []
    available = [r for r in family_rows if r["p50_vs_local"] is not None]
    if available:
        for _ in range(manifest["bootstrap_family_replicates"]):
            sample = [rng.choice(available) for _ in available]
            bootstrap.append(math.exp(statistics.mean(math.log(r["p50_vs_local"]) for r in sample)))
        bootstrap.sort()
    complete = all(r["complete"] for r in family_rows)
    conclusion = {
        "H_correctness": "REFUTED"
        if any(int(r["mismatch_count"]) for r in rows)
        else "FINITE_CHECKS_PASS"
        if complete
        else "INCOMPLETE",
        "H_guard": "INCOMPLETE"
        if not complete
        else "SUPPORTED_ON_FROZEN_SCOPE"
        if sum(r["H_guard_family_pass"] for r in family_rows) >= 3
        else "REFUTED_ON_FROZEN_SCOPE",
        "passing_families": sum(r["H_guard_family_pass"] for r in family_rows),
        "required_families": 3,
        "family_cluster_bootstrap_p50_ratio_95_percentile": [
            bootstrap[int(0.025 * len(bootstrap))],
            bootstrap[min(len(bootstrap) - 1, int(0.975 * len(bootstrap)))],
        ]
        if bootstrap
        else None,
        "uncertainty_limit": "six mechanism families; descriptive paired bootstrap, no universal or novelty claim",
        "novelty": "UNESTABLISHED",
        "external_human_review": "BLOCKED_NOT_PERFORMED",
    }
    (out / "hypotheses.json").write_text(json.dumps(conclusion, indent=2) + "\n")
    text = [
        "# Prospective native guard study",
        "",
        json.dumps(conclusion, indent=2),
        "",
        "| Family | Cases | p50 / local | p50 / global | DAG / local | H-guard | Regressions |",
        "|---|---:|---:|---:|---:|---|---:|",
    ]
    for r in family_rows:

        def fmt(value):
            return "NA" if value is None else f"{value:.3f}"

        text.append(
            f"| {r['family']} | {r['paired_cases']} | {fmt(r['p50_vs_local'])} | {fmt(r['p50_vs_global'])} | {fmt(r['dag_vs_local'])} | {r['H_guard_family_pass']} | {r['runtime_regressions_vs_local']} |"
        )
    text += [
        "",
        "All observations retained. These are native idealized engineering mechanisms with synthetic role assignments, not deployed systems.",
        "Fixed-order reference ROBDD is an additional comparator; low graph size alone is not a win.",
        "Exact source/data hashes, raw timings, process RSS, frontier members and rejected transformations accompany this report.",
    ]
    (out / "study_report.md").write_text("\n".join(text) + "\n")
    return conclusion
