"""Frozen-scope v4 measurements, with equal budgets and retained failures.

Warm construction excludes dependency import, output serialization, metrics and
certificate conversion. Cold startup and proof costs are reported separately.
All workers import the same optional dependencies before construction. This is
a controlled common-environment comparison, not minimal per-backend startup.
"""

import csv
import importlib
import importlib.metadata
import json
import math
import os
import platform
import random
import re
import resource
import statistics
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from hashlib import sha256
from itertools import product
from pathlib import Path
from time import perf_counter, perf_counter_ns

from ..evaluator import operational
from ..metrics import model_metrics
from ..model import ModelError
from ..optimize import expression_only
from ..paper import write_csv
from ..research.kernel import Program
from ..research.study import deadline, measure
from ..symbolic import abc
from ..symbolic.chains import NativeCompiled
from ..symbolic.compile import connectivity_circuit
from ..symbolic.cudd import Compiled
from ..symbolic.equivalence import check
from . import domain

ARMS = ("native-gl", "local-gl", "aig-sift", "direct-sift", "chain-sift", "abc-resyn2")
RATIO_FIELDS = ("build_ratio_direct", "build_ratio_aig", "p50_ratio", "rss_ratio", "bdd_node_ratio")


def dump(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def identity(spec, arm):
    return {
        **{k: spec[k] for k in ("family", "policy", "seed", "n")},
        "case": spec["id"],
        "arm": arm,
    }


def validate_cases(cases, manifest):
    """Reject vacuous, mismatched or path-escaping studies before writing output."""
    if (
        type(cases) is not list
        or not cases
        or type(manifest.get("cases")) is not int
        or manifest["cases"] != len(cases)
    ):
        raise ModelError("case list must be nonempty and match manifest count")
    for key in ("families", "policies", "seeds"):
        values = manifest.get(key)
        if type(values) is not list or not values or len(set(values)) != len(values):
            raise ModelError(f"manifest {key} must be nonempty and unique")
    for key in (
        "construction_seconds",
        "verification_ms",
        "worker_seconds",
        "samples",
        "repeats",
        "bootstrap_replicates",
    ):
        if type(manifest.get(key)) is not int or manifest[key] < 1:
            raise ModelError(f"manifest {key} must be a positive integer")
    if type(manifest.get("bootstrap_seed")) is not int:
        raise ModelError("manifest bootstrap_seed must be an integer")
    identifiers, strata = set(), set()
    for spec in cases:
        name = spec.get("id") if type(spec) is dict else None
        if (
            type(name) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is None
            or name in identifiers
        ):
            raise ModelError("case IDs must be unique safe filename components")
        identifiers.add(name)
        domain.validate(spec)
        stratum = (spec.get("family"), spec.get("policy"), spec.get("seed"))
        if (
            stratum in strata
            or spec.get("family") not in manifest["families"]
            or spec.get("policy") not in manifest["policies"]
            or type(spec.get("seed")) is not int
            or spec["seed"] not in manifest["seeds"]
        ):
            raise ModelError("case family/policy/seed strata must be unique and declared")
        strata.add(stratum)
    expected = set(product(manifest["families"], manifest["policies"], manifest["seeds"]))
    if strata != expected:
        raise ModelError("case inventory must contain every declared family/policy/seed stratum")


def load_inputs(cases_path, manifest_path):
    cases_bytes = Path(cases_path).read_bytes()
    manifest = json.loads(Path(manifest_path).read_text())
    if type(manifest) is not dict or sha256(cases_bytes).hexdigest() != manifest.get(
        "dataset_sha256"
    ):
        raise ModelError("frozen dataset changed")
    cases = json.loads(cases_bytes)
    validate_cases(cases, manifest)
    return cases, manifest


def certified(record):
    return (
        record.get("status") == "COMPLETE"
        and record.get("exit_code", 0) == 0
        and record.get("input_certificate", {}).get("status") == "UNSAT_PREDICATE_EQUIVALENCE"
        and record.get("certificate", {}).get("status") == "UNSAT_FINITE_EQUIVALENCE"
        and (
            record.get("arm") != "abc-resyn2"
            or record.get("abc_cec", {}).get("status") == "EQUIVALENT"
        )
    )


def proof_query(function, timeout_ms):
    """Bound encoding plus solving; a late result cannot acquire a PASS label."""
    started = perf_counter()
    try:
        with deadline(timeout_ms / 1000):
            result = function()
    except TimeoutError:
        result = {"status": "UNKNOWN", "reason": "verification wall deadline exceeded"}
    elapsed = (perf_counter() - started) * 1000
    if elapsed > timeout_ms and result.get("status") in ("COUNTEREXAMPLE", "ENCODING_ERROR"):
        result = {**result, "late": True, "wall_limit_exceeded": True}
    elif elapsed > timeout_ms and result.get("status") != "UNKNOWN":
        result = {
            "status": "UNKNOWN",
            "reason": "verification result exceeded wall deadline",
            "late_result": result,
        }
    return {**result, "wall_ms": elapsed, "wall_limit_ms": timeout_ms}


def worker(spec, manifest, arm, output, abc_binary):
    """One arm in one process. The parent enforces the full worker envelope."""
    if arm not in ARMS:
        raise ModelError("unknown arm")
    domain.validate(spec)
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=False)
    record = identity(spec, arm)
    record.update(
        status="RUNNING", phase="dependency_import", started_at=datetime.now(UTC).isoformat()
    )
    start = perf_counter()

    def checkpoint(phase):
        record["phase"] = phase
        dump(folder / "result.json", record)

    def finish(status):
        record.update(
            status=status, peak_rss_bytes=rss_bytes(), total_seconds=perf_counter() - start
        )
        dump(folder / "result.json", record)
        return record

    try:
        checkpoint("dependency_import")
        imported = perf_counter()
        importlib.import_module("dd.cudd")
        importlib.import_module("z3")
        record["dependency_import_ms"] = (perf_counter() - imported) * 1000
        record["preconstruction_peak_rss_bytes"] = rss_bytes()
        diagram, native_query, circuit, compiled = None, None, None, None
        checkpoint("construction")
        construction = perf_counter()
        stamp = os.environ.get("FAULTGRAPH_V4_SPAWN_NS")
        record["cold_startup_ms"] = (perf_counter_ns() - int(stamp)) / 1e6 if stamp else None
        with deadline(manifest["construction_seconds"]):
            original = domain.model(spec)
            build_input_ms = (perf_counter() - construction) * 1000
            if arm in ("native-gl", "local-gl"):
                result = original if arm == "native-gl" else expression_only(original)
                program = Program.build(result)
                evaluate = program.evaluate

                def native_query(state):
                    return operational(result, state)

            elif arm in ("direct-sift", "chain-sift"):
                compiled = NativeCompiled(original, compress=arm == "chain-sift", reorder=True)
                diagram = compiled.diagram
                evaluate, native_query = diagram.evaluate, compiled.evaluate_native
            else:
                circuit = connectivity_circuit(original, factor=False)
                if arm == "abc-resyn2":
                    result, external = abc.synthesize(
                        circuit,
                        abc_binary,
                        folder / "abc",
                        timeout=manifest["construction_seconds"],
                    )
                    evaluate = result.evaluate
                    record["abc_synthesis"] = external
                else:
                    compiled = Compiled(circuit, reorder=True)
                    diagram = compiled.diagram
                    evaluate, native_query = diagram.evaluate, compiled.evaluate_native
            construction_ms = (perf_counter() - construction) * 1000
        if construction_ms > 1000 * manifest["construction_seconds"]:
            raise TimeoutError("construction completed after its predeclared deadline")
        record.update(
            construction_ms=construction_ms,
            input_build_ms=build_input_ms,
            construction_peak_rss_bytes=rss_bytes(),
            cold_to_ready_ms=None
            if record["cold_startup_ms"] is None
            else record["cold_startup_ms"] + construction_ms,
            source_graph={
                "V": len(original.vertices),
                "logical_E": len(original.edges),
                "physical_E": len(spec["links"]),
            },
            source_metrics=model_metrics(original),
            source_model_sha256=original.digest,
        )
        checkpoint("artifact_and_metrics")
        if diagram is not None:
            artifact = diagram.to_dict()
            metric = {"representation": "BDD", "bdd_nodes": len(diagram.nodes)}
            record["variable_order"] = compiled.order
            if arm in ("direct-sift", "chain-sift"):
                metric.update(
                    symbolic_apply_calls=compiled.apply_calls,
                    sampled_peak_manager_nodes=compiled.peak_manager_nodes,
                    summary_vertices=compiled.reduced_vertices,
                    summary_edges=compiled.reduced_edges,
                    global_chain_obligations=len(compiled.lineage),
                )
                record["chain_lineage"] = compiled.lineage
                record["symbolic_metric_scope"] = (
                    "apply calls count public AND/OR operations, not CPU instructions; "
                    "manager size sampled after each call, not CUDD internal transient peak"
                )
                record["summary_scope"] = (
                    "intermediate graph plus global Boolean obligations, not a standalone equivalent GL graph"
                )
                dump(folder / "chain-lineage.json", compiled.lineage)
            else:
                metric["input_aig_and"] = len(circuit.gates)
                metric["symbolic_apply_calls"] = len(circuit.gates)
        elif arm == "abc-resyn2":
            artifact = result.to_dict()
            metric = {
                "representation": "AIG",
                "aig_and": len(result.gates),
                "input_aig_and": len(circuit.gates),
            }
        else:
            artifact = result.to_dict()
            metric = {"representation": "GL", **model_metrics(result), "dag_ops": program.dag_ops}
        dump(folder / "input-model.json", original.to_dict())
        dump(folder / "output.json", artifact)
        if circuit is not None:
            dump(folder / "before-synthesis.json", circuit.to_dict())
        record.update(
            metrics=metric,
            output_sha256=sha256((folder / "output.json").read_bytes()).hexdigest(),
            output_bytes=(folder / "output.json").stat().st_size,
        )
        checkpoint("verification")
        verification = perf_counter()
        if diagram is not None:
            converted = perf_counter()
            result = diagram.circuit()
            record["certificate_conversion_ms"] = (perf_counter() - converted) * 1000
            metric["certificate_aig_and"] = len(result.gates)
        record["input_certificate"] = proof_query(
            lambda: domain.input_certificate(
                spec, original, folder / "input-policy.smt2", manifest["verification_ms"]
            ),
            manifest["verification_ms"],
        )
        checkpoint("output_equivalence")
        record["certificate"] = proof_query(
            lambda: check(
                original,
                result,
                timeout_ms=manifest["verification_ms"],
                smt_path=folder / "equivalence.smt2",
            ),
            manifest["verification_ms"],
        )
        if arm == "abc-resyn2":
            checkpoint("abc_cec")
            record["abc_cec"] = proof_query(
                lambda: abc.equivalence(
                    abc_binary, folder / "abc", timeout=manifest["verification_ms"] / 1000
                ),
                manifest["verification_ms"],
            )
        record["verification_ms"] = (perf_counter() - verification) * 1000
        statuses = [record["input_certificate"]["status"], record["certificate"]["status"]]
        if arm == "abc-resyn2":
            statuses.append(record["abc_cec"]["status"])
        if "COUNTEREXAMPLE" in statuses or "ENCODING_ERROR" in statuses:
            return finish("COUNTEREXAMPLE")
        all_proven = statuses == ["UNSAT_PREDICATE_EQUIVALENCE", "UNSAT_FINITE_EQUIVALENCE"] + (
            ["EQUIVALENT"] if arm == "abc-resyn2" else []
        )
        checkpoint("independent_oracle")
        rng = random.Random(19281 + spec["seed"] + spec["n"])
        samples = {
            "uniform": [
                tuple(rng.randrange(2) for _ in range(spec["n"]))
                for _ in range(manifest["samples"])
            ],
            "p95": [
                tuple(int(rng.random() < 0.95) for _ in range(spec["n"]))
                for _ in range(manifest["samples"])
            ],
        }
        states = (
            list(product((0, 1), repeat=spec["n"]))
            if spec["n"] <= 12
            else samples["uniform"] + samples["p95"] + [(0,) * spec["n"], (1,) * spec["n"]]
        )
        truth = []
        for state in states:
            expected = domain.oracle(spec, state)
            truth.append(expected)
            observed = bool(evaluate(state))
            native_value = bool(native_query(state)) if native_query is not None else observed
            if observed != expected or native_value != expected:
                record.update(
                    witness="".join(map(str, state)),
                    expected=expected,
                    observed=observed,
                    native_observed=native_value,
                )
                return finish("COUNTEREXAMPLE")
        record.update(
            exhaustive_states=len(states) if spec["n"] <= 12 else 0,
            sampled_checks=len(states) if spec["n"] > 12 else 0,
            truth_sha256=sha256(bytes(truth)).hexdigest(),
            state_sha256=sha256(bytes(bit for state in states for bit in state)).hexdigest(),
            oracle_scope="exhaustive finite domain"
            if spec["n"] <= 12
            else "supplementary samples plus all-zero/all-one; not a proof",
        )
        checkpoint("query_timing")
        record["timing"] = {
            key: measure(evaluate, values, manifest["repeats"]) for key, values in samples.items()
        }
        if native_query is not None:
            record["native_interface_timing"] = {
                key: measure(native_query, values, manifest["repeats"])
                for key, values in samples.items()
            }
        if diagram is not None:
            checkpoint("reliability")
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
            record["reliability_law"] = (
                "q=0.1 all processors failed; otherwise original independent processor law; no edge independence assumed"
            )
        record["phase"] = "finished"
        record["measurement"] = (
            "fresh sequential worker; 16 query warmups; warm build excludes import/serialization/metrics/proof conversion; total peak RSS includes all phases"
        )
        return finish("COMPLETE" if all_proven else "UNCERTIFIED")
    except Exception as error:
        record.update(
            error=str(error), error_type=type(error).__name__, traceback=traceback.format_exc()
        )
        return finish(
            "TIMEOUT"
            if isinstance(error, TimeoutError)
            else "RESOURCE_OR_MODEL_ERROR"
            if isinstance(error, (MemoryError, ModelError))
            else "ERROR"
        )


def flatten(record):
    names = (
        "case",
        "family",
        "policy",
        "seed",
        "n",
        "arm",
        "status",
        "phase",
        "dependency_import_ms",
        "cold_startup_ms",
        "construction_ms",
        "cold_to_ready_ms",
        "verification_ms",
        "construction_peak_rss_bytes",
        "peak_rss_bytes",
        "output_bytes",
        "output_sha256",
        "exhaustive_states",
        "sampled_checks",
        "truth_sha256",
        "total_seconds",
        "exit_code",
    )
    row = {key: record.get(key) for key in names}
    row.update(record.get("metrics", {}))
    row.update(
        p50_ms=record.get("timing", {}).get("uniform", {}).get("p50_ms"),
        p95_ms=record.get("timing", {}).get("uniform", {}).get("p95_ms"),
        high_working_p50_ms=record.get("timing", {}).get("p95", {}).get("p50_ms"),
    )
    return row


def source_hashes():
    source = Path(__file__).resolve().parents[1]
    return {
        "src/faultgraph/" + str(p.relative_to(source)): sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*.py"))
    }


def run(cases_path, manifest_path, output, abc_binary):
    path, manifest_path, out = (
        Path(cases_path).resolve(),
        Path(manifest_path).resolve(),
        Path(output),
    )
    if out.exists():
        raise ModelError("new output directory required")
    cases, manifest = load_inputs(path, manifest_path)
    binary = Path(abc_binary).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ModelError("executable ABC binary required")
    out.mkdir(parents=True)
    (out / "cases.json").write_bytes(path.read_bytes())
    (out / "manifest.json").write_bytes(manifest_path.read_bytes())
    system = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "started_at": datetime.now(UTC).isoformat(),
        "source_hashes": source_hashes(),
        "abc_binary_sha256": sha256(binary.read_bytes()).hexdigest(),
        "dependencies": {name: importlib.metadata.version(name) for name in ("dd", "z3-solver")},
        "arm_rotation": list(ARMS),
        "common_imports": ["dd.cudd", "z3"],
        "query_warmups": 16,
        "cudd_memory_bytes": 256 * 1024 * 1024,
        "node_gate_limit": 100000,
    }
    dump(out / "system_info.json", system)
    started, results = perf_counter(), []
    with (out / "raw_runs.jsonl").open("w") as raw:
        for index, spec in enumerate(cases):
            arms = ARMS[index % len(ARMS) :] + ARMS[: index % len(ARMS)]
            for arm in arms:
                folder = (out / "runs" / f"{spec['id']}-{arm}").resolve()
                command = [
                    sys.executable,
                    "-m",
                    "faultgraph.chainstudy",
                    "worker",
                    str(path),
                    "--manifest",
                    str(manifest_path),
                    "--case",
                    str(index),
                    "--arm",
                    arm,
                    "--output",
                    str(folder),
                    "--abc",
                    str(binary),
                ]
                spawn = perf_counter_ns()
                try:
                    child = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=manifest["worker_seconds"],
                        env={
                            **os.environ,
                            "PYTHONHASHSEED": "0",
                            "FAULTGRAPH_V4_SPAWN_NS": str(spawn),
                        },
                    )
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / "stdout.log").write_text(child.stdout)
                    (folder / "stderr.log").write_text(child.stderr)
                    record_path = folder / "result.json"
                    record = (
                        json.loads(record_path.read_text())
                        if record_path.exists()
                        else {
                            **identity(spec, arm),
                            "status": "ERROR",
                            "phase": "worker_startup",
                            "error": "worker produced no record",
                        }
                    )
                    record["exit_code"] = child.returncode
                    if record.get("status") == "RUNNING" or (
                        record.get("status") == "COMPLETE" and child.returncode != 0
                    ):
                        record["status"] = "ERROR"
                        record["error"] = "worker exited without a successful final record"
                except subprocess.TimeoutExpired as error:
                    folder.mkdir(parents=True, exist_ok=True)
                    prior = folder / "result.json"
                    record = (
                        json.loads(prior.read_text()) if prior.exists() else identity(spec, arm)
                    )
                    record.update(
                        status="TIMEOUT",
                        timed_out_phase=record.get("phase", "worker_startup"),
                        phase="worker_envelope",
                        seconds_limit=manifest["worker_seconds"],
                        exit_code=None,
                    )
                    for name, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                        (folder / f"{name}.log").write_bytes(
                            value if isinstance(value, bytes) else (value or "").encode()
                        )
                record["worker_wall_ms"] = (perf_counter_ns() - spawn) / 1e6
                record["command"] = command
                dump(folder / "result.json", record)
                raw.write(json.dumps(record, allow_nan=False) + "\n")
                raw.flush()
                results.append(record)
                dump(
                    out / "progress.json",
                    {
                        "completed": len(results),
                        "planned": len(cases) * len(ARMS),
                        "failures": sum(not certified(r) for r in results),
                        "last": spec["id"] + ":" + arm,
                        "seconds": perf_counter() - started,
                    },
                )
            print(f"{index + 1}/{len(cases)} cases; {len(results)} arm runs", flush=True)
    rows = [flatten(record) for record in results]
    with (out / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, sorted(set().union(*(row.keys() for row in rows))))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "status": "COMPLETE" if all(certified(r) for r in results) else "INCOMPLETE",
        "cases": len(cases),
        "arm_runs": len(results),
        "failures": sum(not certified(r) for r in results),
        "seconds": perf_counter() - started,
        "exhaustive_state_comparisons": sum(r.get("exhaustive_states", 0) for r in results),
        "sampled_state_checks": sum(r.get("sampled_checks", 0) for r in results),
        "exact_symbolic_certificates": sum(
            r.get("certificate", {}).get("status") == "UNSAT_FINITE_EQUIVALENCE" for r in results
        ),
    }
    finding = analyze(out)
    summary["analysis_complete"] = finding["complete"]
    summary["evidence_errors"] = finding["evidence_errors"]
    if not finding["complete"]:
        summary["status"] = "INCOMPLETE"
    dump(out / "summary.json", summary)
    return summary


def analyze(output):
    """Rebuild derived comparisons without changing raw rows or reclassifying failures."""
    out = Path(output)
    cases, manifest = load_inputs(out / "cases.json", out / "manifest.json")
    rows = [json.loads(line) for line in (out / "raw_runs.jsonl").read_text().splitlines()]
    by = {(r.get("case"), r.get("arm")): r for r in rows}
    expected = {(spec["id"], arm) for spec in cases for arm in ARMS}
    complete = set(by) == expected and len(by) == len(rows) and all(certified(r) for r in rows)
    evidence_errors = []
    invalid_pairs = set()
    for spec in cases:
        before = len(evidence_errors)
        certified_rows = []
        for arm in ARMS:
            row = by.get((spec["id"], arm), {})
            if not row:
                continue
            if any(row.get(k) != v for k, v in identity(spec, arm).items()):
                evidence_errors.append(f"{spec['id']}:{arm}: identity mismatch")
            if certified(row):
                certified_rows.append(row)
                for name, count in (
                    ("exhaustive_states", 2 ** spec["n"] if spec["n"] <= 12 else 0),
                    ("sampled_checks", 0 if spec["n"] <= 12 else 2 * manifest["samples"] + 2),
                ):
                    if type(row.get(name)) is not int or row[name] != count:
                        evidence_errors.append(f"{spec['id']}:{arm}: {name} mismatch")
                for name in ("source_model_sha256", "state_sha256", "truth_sha256"):
                    if (
                        type(row.get(name)) is not str
                        or re.fullmatch("[0-9a-f]{64}", row[name]) is None
                    ):
                        evidence_errors.append(f"{spec['id']}:{arm}: missing or invalid {name}")
        for name in ("source_model_sha256", "state_sha256", "truth_sha256"):
            if len({row.get(name) for row in certified_rows}) > 1:
                evidence_errors.append(f"{spec['id']}: cross-arm {name} mismatch")
        if len(evidence_errors) != before:
            invalid_pairs.add(spec["id"])
    complete = complete and not evidence_errors
    paired = []
    for spec in cases:
        entry = {key: spec[key] for key in ("family", "seed", "policy")}
        entry["case"] = spec["id"]
        a, b, c = (
            by.get((spec["id"], arm), {}) for arm in ("chain-sift", "direct-sift", "aig-sift")
        )
        if spec["id"] in invalid_pairs:
            entry["status"] = "INVALID_PAIRING_EVIDENCE"
        elif not all(certified(r) for r in (a, b, c)):
            entry["status"] = "MISSING_OR_UNCERTIFIED"
        else:
            try:
                for row in (a, b, c):
                    values = (
                        row["construction_ms"],
                        row["peak_rss_bytes"],
                        row["timing"]["uniform"]["p50_ms"],
                    )
                    if not all(
                        type(value) in (int, float) and math.isfinite(value) and value > 0
                        for value in values
                    ):
                        raise ValueError("invalid construction/query/RSS metric")
                entry.update(
                    build_ratio_direct=a["construction_ms"] / b["construction_ms"],
                    build_ratio_aig=a["construction_ms"] / c["construction_ms"],
                    p50_ratio=a["timing"]["uniform"]["p50_ms"] / b["timing"]["uniform"]["p50_ms"],
                    rss_ratio=a["peak_rss_bytes"] / b["peak_rss_bytes"],
                    bdd_node_ratio=a["metrics"]["bdd_nodes"] / max(1, b["metrics"]["bdd_nodes"]),
                )
                if not all(math.isfinite(entry[k]) and entry[k] >= 0 for k in RATIO_FIELDS):
                    raise ValueError("invalid ratio")
                entry["status"] = "PAIRED"
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                entry["status"] = "INVALID_METRICS"
                complete = False
        paired.append(entry)
    families = []
    for family in manifest["families"]:
        members = [p for p in paired if p["family"] == family]
        entry = {
            "family": family,
            "paired": sum(p["status"] == "PAIRED" for p in members),
            "required": len(members),
            "qualifies": False,
        }
        if members and all(p["status"] == "PAIRED" for p in members):
            for metric in RATIO_FIELDS:
                entry[metric] = statistics.median(
                    statistics.median(r[metric] for r in members if r["seed"] == seed)
                    for seed in manifest["seeds"]
                )
            entry["qualifies"] = (
                entry["build_ratio_direct"] <= 0.8
                and entry["build_ratio_aig"] <= 0.8
                and entry["p50_ratio"] <= 1.1
                and entry["rss_ratio"] <= 1.1
            )
        families.append(entry)
    count = sum(f["qualifies"] for f in families)
    finding = {
        "status": "SUPPORTED_ON_FROZEN_SCOPE"
        if complete and count >= 3
        else "REFUTED_ON_FROZEN_SCOPE"
        if complete
        else "INCONCLUSIVE",
        "complete": complete,
        "qualifying_families": count,
        "required": 3,
        "family_count": len(families),
        "novelty": "UNESTABLISHED",
        "external_human_review": "NOT_PERFORMED",
        "evidence_errors": evidence_errors,
        "scope": "six provider/core clusters with paired policy/seed medians; not a universal claim",
    }
    if manifest.get("study_id") != "native-chain-v4":
        finding["status"] = "DEVELOPMENT_ONLY" if complete else "INCONCLUSIVE"
        finding["scope"] = "development data; no prospective research conclusion"
    if complete:
        rng = random.Random(manifest["bootstrap_seed"])
        for metric in ("build_ratio_direct", "build_ratio_aig", "p50_ratio", "rss_ratio"):
            boot = sorted(
                statistics.median(rng.choice(families)[metric] for _ in families)
                for _ in range(manifest["bootstrap_replicates"])
            )
            finding[f"descriptive_cluster_bootstrap_{metric}_95_percentile"] = [
                boot[int(0.025 * len(boot))],
                boot[min(len(boot) - 1, int(0.975 * len(boot)))],
            ]
    dump(out / "paired.json", paired)
    dump(out / "families.json", families)
    dump(out / "hypothesis.json", finding)
    write_csv(
        out / "family_results.csv",
        [
            {k: f.get(k) for k in ("family", "paired", "required", *RATIO_FIELDS, "qualifies")}
            for f in families
        ],
    )
    return finding
