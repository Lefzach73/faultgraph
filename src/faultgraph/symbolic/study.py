"""v3 prospective measurements; no hidden tuning or omitted failed arms."""

import csv
import json
import os
import platform
import random
import re
import resource
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from itertools import product
from pathlib import Path
from time import perf_counter

from ..evaluator import operational
from ..metrics import model_metrics
from ..model import Edge, GLModel, ModelError
from ..optimize import expression_only
from ..paper import write_csv
from ..research.kernel import Program
from ..research.study import deadline, measure
from . import abc, native
from .compile import connectivity_circuit, edge_blocks
from .cudd import Compiled
from .equivalence import check, graph_formula

ARMS = (
    "published",
    "local",
    "cudd-fixed",
    "cudd-sift",
    "block-fixed",
    "block-sift",
    "abc-mono",
    "abc-block",
)


def dump(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def input_certificate(spec, model, folder, timeout_ms):
    """Exact native-rule to predicate equivalence, plus exact endpoint equality."""
    import z3

    if tuple(spec["vertices"]) != model.vertices or len(spec["links"]) != len(model.edges):
        raise ValueError("source topology changed")
    xs = [z3.Bool(f"x{i}") for i in range(1, spec["n"] + 1)]
    diffs = []
    for edge, rule in zip(model.edges, spec["links"], strict=True):
        if (edge.u, edge.v) != (rule["u"], rule["v"]):
            raise ValueError("source edge endpoint changed")
        # This arithmetic resource rule is independent of the AST constructor.
        count = z3.Sum([z3.If(xs[i - 1], 1, 0) for i in rule["processors"]])
        target = count >= (2 if spec["policy"] == "shared" else 1)
        graph = GLModel(spec["n"], ("a", "b"), (Edge("e", "a", "b", edge.predicate),))
        diffs.append(z3.Xor(graph_formula(graph, xs), target))
    solver = z3.Solver()
    solver.set(timeout=timeout_ms, random_seed=0)
    solver.add(z3.Or(*diffs))
    (folder / "input-policy.smt2").write_text(solver.to_smt2())
    start = perf_counter()
    answer = solver.check()
    return {
        "status": "UNSAT_PREDICATE_EQUIVALENCE"
        if answer == z3.unsat
        else "COUNTEREXAMPLE"
        if answer == z3.sat
        else "UNKNOWN",
        "topology_match": True,
        "solver_seconds": perf_counter() - start,
        "reason": solver.reason_unknown() if answer == z3.unknown else None,
        "scope": "every link matches the independent arithmetic rule for all assignments; exact persistent topology match",
    }


def worker(spec, manifest, arm, output, abc_binary):
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=False)
    if arm not in ARMS:
        raise ValueError("unknown arm")
    record = {
        "case": spec["id"],
        "family": spec["family"],
        "policy": spec["policy"],
        "seed": spec["seed"],
        "n": spec["n"],
        "arm": arm,
    }
    start = perf_counter()
    diagram = None
    native_query = None
    construction = perf_counter()
    with deadline(manifest["construction_seconds"]):
        original = native.model(spec)
        build_input_ms = (perf_counter() - construction) * 1000
        if arm in ("published", "local"):
            result = original if arm == "published" else expression_only(original)
            program = Program.build(result)
            evaluate = program.evaluate

            def native_query(s):
                return operational(result, s)

            artifact = result.to_dict()
            metric = {"representation": "GL", **model_metrics(result), "dag_ops": program.dag_ops}
        else:
            circuit = connectivity_circuit(
                original, factor=arm.startswith("block") or arm == "abc-block"
            )
            dump(folder / "before-synthesis.json", circuit.to_dict())
            if arm.startswith("abc"):
                result, external = abc.synthesize(
                    circuit, abc_binary, folder / "abc", timeout=manifest["construction_seconds"]
                )
                evaluate = result.evaluate
                artifact = result.to_dict()
                metric = {
                    "representation": "AIG",
                    "aig_and": len(result.gates),
                    "input_aig_and": len(circuit.gates),
                }
                record["abc_synthesis"] = external
            else:
                compiled = Compiled(circuit, reorder=arm.endswith("sift"))
                diagram = compiled.diagram
                result = diagram.circuit()
                evaluate = diagram.evaluate
                native_query = compiled.evaluate_native
                artifact = diagram.to_dict()
                metric = {
                    "representation": "BDD",
                    "bdd_nodes": len(diagram.nodes),
                    "certificate_aig_and": len(result.gates),
                    "input_aig_and": len(circuit.gates),
                }
                record["variable_order"] = compiled.order
        construction_ms = (perf_counter() - construction) * 1000
    dump(folder / "output.json", artifact)
    record.update(
        metrics=metric,
        construction_ms=construction_ms,
        input_build_ms=build_input_ms,
        output_sha256=sha256((folder / "output.json").read_bytes()).hexdigest(),
        output_bytes=(folder / "output.json").stat().st_size,
        source_graph={"V": len(original.vertices), "E": len(original.edges)},
        block_edge_counts=[len(b) for b in edge_blocks(original)],
    )
    verification = perf_counter()
    policy_certificate = input_certificate(spec, original, folder, manifest["verification_ms"])
    cert = check(
        original,
        result,
        timeout_ms=manifest["verification_ms"],
        smt_path=folder / "equivalence.smt2",
    )
    record.update(input_certificate=policy_certificate, certificate=cert)
    if arm.startswith("abc"):
        record["abc_cec"] = abc.equivalence(
            abc_binary, folder / "abc", timeout=manifest["verification_ms"] / 1000
        )
    record["verification_ms"] = (perf_counter() - verification) * 1000
    if (
        policy_certificate["status"] != "UNSAT_PREDICATE_EQUIVALENCE"
        or cert["status"] != "UNSAT_FINITE_EQUIVALENCE"
        or (arm.startswith("abc") and record["abc_cec"]["status"] != "EQUIVALENT")
    ):
        record["status"] = "UNCERTIFIED"
        dump(folder / "result.json", record)
        return record
    rng = random.Random(19281 + spec["seed"] + spec["n"])
    samples = {
        "uniform": [
            tuple(rng.randrange(2) for _ in range(spec["n"])) for _ in range(manifest["samples"])
        ],
        "p95": [
            tuple(int(rng.random() < 0.95) for _ in range(spec["n"]))
            for _ in range(manifest["samples"])
        ],
    }
    domain = (
        list(product((0, 1), repeat=spec["n"]))
        if spec["n"] <= 12
        else samples["uniform"] + samples["p95"] + [(0,) * spec["n"], (1,) * spec["n"]]
    )
    truth = []
    for state in domain:
        expected = native.oracle(spec, state)
        truth.append(expected)
        if bool(evaluate(state)) != expected or (
            native_query is not None and bool(native_query(state)) != expected
        ):
            record.update(
                status="COUNTEREXAMPLE", witness="".join(map(str, state)), expected=expected
            )
            dump(folder / "result.json", record)
            return record
    record.update(
        exhaustive_states=len(domain) if spec["n"] <= 12 else 0,
        sampled_checks=len(domain) if spec["n"] > 12 else 0,
        truth_sha256=sha256(bytes(truth)).hexdigest(),
    )
    record["timing"] = {
        key: measure(evaluate, values, manifest["repeats"]) for key, values in samples.items()
    }
    if native_query is not None:
        record["native_interface_timing"] = {
            key: measure(native_query, values, manifest["repeats"])
            for key, values in samples.items()
        }
    if diagram is not None:
        laws = []
        for p in (0.8, 0.9, 0.99):
            independent = diagram.reliability([p] * spec["n"])
            laws.append(
                {
                    "working_probability": p,
                    "independent": independent,
                    "common_cause_q": 0.1,
                    "correlated": 0.9 * independent + 0.1 * diagram.evaluate((0,) * spec["n"]),
                }
            )
        record["reliability"] = laws
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    record.update(
        status="COMPLETE",
        peak_rss_bytes=rss if sys.platform == "darwin" else rss * 1024,
        total_seconds=perf_counter() - start,
        measurement="fresh sequential process; peak RSS includes construction, verification and timed queries",
    )
    dump(folder / "result.json", record)
    return record


def flatten(record):
    base = {
        key: record.get(key)
        for key in (
            "case",
            "family",
            "policy",
            "seed",
            "n",
            "arm",
            "status",
            "construction_ms",
            "verification_ms",
            "peak_rss_bytes",
            "output_bytes",
            "output_sha256",
            "exhaustive_states",
            "sampled_checks",
            "truth_sha256",
            "total_seconds",
        )
    }
    base.update(record.get("metrics", {}))
    base.update(
        {
            "p50_ms": record.get("timing", {}).get("uniform", {}).get("p50_ms"),
            "p95_ms": record.get("timing", {}).get("uniform", {}).get("p95_ms"),
            "high_working_p50_ms": record.get("timing", {}).get("p95", {}).get("p50_ms"),
        }
    )
    return base


def run(manifest_path, output, abc_binary):
    path, out = Path(manifest_path), Path(output)
    if out.exists():
        raise ValueError("new output directory required")
    manifest = json.loads(path.read_text())
    data_path = path.parent / "cases.json"
    if sha256(data_path.read_bytes()).hexdigest() != manifest["dataset_sha256"]:
        raise ValueError("frozen dataset changed")
    cases = json.loads(data_path.read_text())
    if (
        type(cases) is not list
        or not cases
        or type(manifest.get("cases")) is not int
        or manifest["cases"] != len(cases)
    ):
        raise ModelError("case list must be nonempty and match manifest count")
    identifiers = set()
    for spec in cases:
        name = spec.get("id") if type(spec) is dict else None
        if (
            type(name) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is None
            or name in identifiers
        ):
            raise ModelError("case IDs must be unique safe filename components")
        identifiers.add(name)
    out.mkdir(parents=True)
    (out / "manifest.json").write_bytes(path.read_bytes())
    (out / "cases.json").write_bytes(data_path.read_bytes())
    system = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "started_at": datetime.now(UTC).isoformat(),
        "source_hashes": {
            str(p): sha256(p.read_bytes()).hexdigest()
            for p in Path("src/faultgraph/symbolic").glob("*.py")
        },
        "abc_binary_sha256": sha256(Path(abc_binary).read_bytes()).hexdigest(),
    }
    dump(out / "system_info.json", system)
    start, results = perf_counter(), []
    with (out / "raw_runs.jsonl").open("w") as raw:
        for index, spec in enumerate(cases):
            arms = ARMS[index % len(ARMS) :] + ARMS[: index % len(ARMS)]
            for arm in arms:
                folder = out / "runs" / f"{spec['id']}-{arm}"
                command = [
                    sys.executable,
                    "-m",
                    "faultgraph.symbolic",
                    "worker",
                    "--manifest",
                    str(path),
                    "--case",
                    str(index),
                    "--arm",
                    arm,
                    "--output",
                    str(folder),
                    "--abc",
                    str(Path(abc_binary).resolve()),
                ]
                try:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=manifest["worker_seconds"],
                        env={**os.environ, "PYTHONHASHSEED": "0"},
                    )
                    record_path = folder / "result.json"
                    if record_path.exists():
                        record = json.loads(record_path.read_text())
                    else:
                        record = {
                            "case": spec["id"],
                            "family": spec["family"],
                            "policy": spec["policy"],
                            "seed": spec["seed"],
                            "n": spec["n"],
                            "arm": arm,
                            "status": "ERROR",
                            "stderr": result.stderr[-8000:],
                            "stdout": result.stdout[-2000:],
                        }
                    record["exit_code"] = result.returncode
                except subprocess.TimeoutExpired as error:
                    record = {
                        "case": spec["id"],
                        "family": spec["family"],
                        "policy": spec["policy"],
                        "seed": spec["seed"],
                        "n": spec["n"],
                        "arm": arm,
                        "status": "TIMEOUT",
                        "phase": "worker",
                        "seconds_limit": manifest["worker_seconds"],
                        "stderr": str(error.stderr or "")[-2000:],
                    }
                raw.write(json.dumps(record) + "\n")
                raw.flush()
                results.append(record)
                dump(
                    out / "progress.json",
                    {
                        "completed": len(results),
                        "planned": len(cases) * len(ARMS),
                        "failures": sum(r["status"] != "COMPLETE" for r in results),
                        "last": spec["id"] + ":" + arm,
                        "seconds": perf_counter() - start,
                    },
                )
            print(f"{index + 1}/{len(cases)} cases; {len(results)} arm runs", flush=True)
    rows = [flatten(record) for record in results]
    fields = sorted(set().union(*(r.keys() for r in rows)))
    with (out / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "status": "COMPLETE" if all(r["status"] == "COMPLETE" for r in results) else "INCOMPLETE",
        "cases": len(cases),
        "arm_runs": len(results),
        "failures": sum(r["status"] != "COMPLETE" for r in results),
        "seconds": perf_counter() - start,
        "exhaustive_state_comparisons": sum(r.get("exhaustive_states", 0) for r in results),
        "sampled_state_checks": sum(r.get("sampled_checks", 0) for r in results),
        "exact_symbolic_certificates": sum(
            r.get("certificate", {}).get("status") == "UNSAT_FINITE_EQUIVALENCE" for r in results
        ),
    }
    dump(out / "summary.json", summary)
    analyze(out)
    return summary


def analyze(output):
    out = Path(output)
    manifest = json.loads((out / "manifest.json").read_text())
    cases = json.loads((out / "cases.json").read_text())
    rows = [json.loads(line) for line in (out / "raw_runs.jsonl").read_text().splitlines()]
    by = {(r["case"], r["arm"]): r for r in rows}
    complete = len(by) == len(rows) == len(cases) * len(ARMS) and all(
        by.get((s["id"], arm), {}).get("status") == "COMPLETE" for s in cases for arm in ARMS
    )
    paired = []
    for spec in cases:
        a, b = by.get((spec["id"], "block-sift"), {}), by.get((spec["id"], "cudd-sift"), {})
        if a.get("status") != "COMPLETE" or b.get("status") != "COMPLETE":
            paired.append(
                {
                    "case": spec["id"],
                    "family": spec["family"],
                    "seed": spec["seed"],
                    "status": "MISSING",
                }
            )
            continue
        paired.append(
            {
                "case": spec["id"],
                "family": spec["family"],
                "seed": spec["seed"],
                "status": "PAIRED",
                "build_ratio": a["construction_ms"] / b["construction_ms"],
                "p50_ratio": a["timing"]["uniform"]["p50_ms"] / b["timing"]["uniform"]["p50_ms"],
                "rss_ratio": a["peak_rss_bytes"] / b["peak_rss_bytes"],
                "bdd_node_ratio": a["metrics"]["bdd_nodes"] / max(1, b["metrics"]["bdd_nodes"]),
            }
        )
    families = []
    for family in manifest["families"]:
        members = [r for r in paired if r["family"] == family]
        entry = {
            "family": family,
            "paired": sum(r["status"] == "PAIRED" for r in members),
            "required": len(members),
        }
        if all(r["status"] == "PAIRED" for r in members):
            for metric in ("build_ratio", "p50_ratio", "rss_ratio", "bdd_node_ratio"):
                entry[metric] = statistics.median(
                    statistics.median(r[metric] for r in members if r["seed"] == seed)
                    for seed in manifest["seeds"]
                )
            entry["qualifies"] = (
                entry["build_ratio"] <= 0.8
                and entry["p50_ratio"] <= 1.1
                and entry["rss_ratio"] <= 1.1
            )
        else:
            entry["qualifies"] = False
        families.append(entry)
    count = sum(r["qualifies"] for r in families)
    finding = {
        "status": "SUPPORTED_ON_FROZEN_SCOPE"
        if complete and count >= 3
        else "REFUTED_ON_FROZEN_SCOPE"
        if complete
        else "INCONCLUSIVE",
        "complete": complete,
        "qualifying_families": count,
        "required": 3,
        "novelty": "UNESTABLISHED",
        "external_human_review": "NOT_PERFORMED",
    }
    if complete:
        rng = random.Random(manifest["bootstrap_seed"])
        boot = sorted(
            statistics.median(rng.choice(families)["build_ratio"] for _ in families)
            for _ in range(manifest["bootstrap_replicates"])
        )
        finding["descriptive_family_bootstrap_build_ratio_95_percentile"] = [
            boot[int(0.025 * len(boot))],
            boot[int(0.975 * len(boot))],
        ]
    dump(out / "paired.json", paired)
    dump(out / "families.json", families)
    dump(out / "hypothesis.json", finding)
    write_csv(
        out / "family_results.csv",
        [
            {
                k: f.get(k)
                for k in (
                    "family",
                    "paired",
                    "required",
                    "build_ratio",
                    "p50_ratio",
                    "rss_ratio",
                    "bdd_node_ratio",
                    "qualifies",
                )
            }
            for f in families
        ],
    )
    return finding
