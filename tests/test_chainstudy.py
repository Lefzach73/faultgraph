"""Development-only integration and failure controls; never use v4 holdout inputs."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from hashlib import sha256
from itertools import product
from pathlib import Path

import pytest

from faultgraph.chainstudy import domain, study
from faultgraph.chainstudy.__main__ import compile_model
from faultgraph.expr import FALSE
from faultgraph.model import Edge, GLModel, ModelError
from faultgraph.symbolic.__main__ import load

ROOT = Path(__file__).resolve().parents[1]
ABC = ROOT / "work/v3/abc/abc"


def toy():
    return {
        "id": "development-parallel-triangle",
        "family": "development",
        "policy": "single",
        "seed": 17,
        "n": 4,
        "vertices": ["a", "b", "c"],
        "links": [
            {"u": "a", "v": "b", "processors": [1]},
            {"u": "b", "v": "a", "processors": [2]},
            {"u": "b", "v": "c", "processors": [3]},
            {"u": "a", "v": "c", "processors": [4]},
        ],
    }


def inputs(folder):
    folder.mkdir(parents=True, exist_ok=True)
    cases = [toy()]
    case_path, manifest_path = folder / "cases.json", folder / "manifest.json"
    study.dump(case_path, cases)
    manifest = {
        "study_id": "development-only",
        "cases": 1,
        "families": ["development"],
        "policies": ["single"],
        "seeds": [17],
        "construction_seconds": 30,
        "verification_ms": 60000,
        "worker_seconds": 180,
        "samples": 16,
        "repeats": 2,
        "bootstrap_seed": 3,
        "bootstrap_replicates": 100,
        "dataset_sha256": sha256(case_path.read_bytes()).hexdigest(),
    }
    study.dump(manifest_path, manifest)
    return case_path, manifest_path, manifest


def optional_backends():
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")


def test_six_arm_process_isolation_certificates_parallel_oracle_and_costs(tmp_path):
    optional_backends()
    if not ABC.is_file():
        pytest.skip("real pinned ABC binary not installed")
    cases, manifest, _ = inputs(tmp_path / "input")
    output = tmp_path / "smoke"
    result = study.run(cases, manifest, output, ABC)
    assert result["status"] == "COMPLETE"
    assert result["arm_runs"] == result["exact_symbolic_certificates"] == 6
    assert result["exhaustive_state_comparisons"] == 6 * 16
    rows = [json.loads(line) for line in (output / "raw_runs.jsonl").read_text().splitlines()]
    assert {r["arm"] for r in rows} == set(study.ARMS)
    assert len({r["truth_sha256"] for r in rows}) == 1
    assert len({r["state_sha256"] for r in rows}) == 1
    for row in rows:
        assert study.certified(row)
        assert row["cold_to_ready_ms"] >= row["construction_ms"] > 0
        assert row["cold_startup_ms"] >= row["dependency_import_ms"] > 0
        assert row["peak_rss_bytes"] >= row["construction_peak_rss_bytes"] > 0
        assert row["source_graph"] == {"V": 3, "logical_E": 3, "physical_E": 4}
        assert len(row["timing"]["uniform"]["raw_ns"]) == 32
        folder = output / "runs" / f"{row['case']}-{row['arm']}"
        assert json.loads((folder / "result.json").read_text()) == row
        assert (folder / "output.json").exists()
        assert sha256((folder / "output.json").read_bytes()).hexdigest() == row["output_sha256"]
    bdds = [r for r in rows if r["arm"].endswith("sift")]
    for law_index in range(3):
        values = [r["reliability"][law_index]["independent"] for r in bdds]
        assert max(values) - min(values) < 1e-12
    assert study.analyze(output)["status"] == "DEVELOPMENT_ONLY"
    assert (output / "system_info.json").read_text().find("src/faultgraph/expr.py") >= 0
    # Valid-looking timing rows cannot substitute another source, state set or
    # truth table, nor omit the independently checked domain inventory.
    for field, invalid in (
        ("family", "wrong-family"),
        ("truth_sha256", "0" * 64),
        ("state_sha256", "0" * 64),
        ("source_model_sha256", "0" * 64),
        ("exhaustive_states", 0),
    ):
        changed = deepcopy(rows)
        changed[0][field] = invalid
        (output / "raw_runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in changed))
        finding = study.analyze(output)
        assert finding["status"] == "INCONCLUSIVE" and finding["evidence_errors"]
    # A copied COMPLETE label does not turn an actual UNKNOWN certificate green.
    rows[0]["certificate"]["status"] = "UNKNOWN"
    (output / "raw_runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert study.analyze(output)["status"] == "INCONCLUSIVE"
    # Missing/duplicate accounting cannot silently disappear in the dictionary.
    (output / "raw_runs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows[1:] + [rows[1]])
    )
    assert not study.analyze(output)["complete"]


@pytest.mark.parametrize("bad", [[], {}, ["../escape"], ["a/b"], [""], [None], ["x", "x"]])
def test_invalid_case_inventory_rejected_before_output(tmp_path, bad):
    cases, manifest_path, manifest = inputs(tmp_path / "input")
    values = (
        bad if not isinstance(bad, list) or not bad else [{**toy(), "id": name} for name in bad]
    )
    study.dump(cases, values)
    manifest["cases"] = len(values)
    manifest["dataset_sha256"] = sha256(cases.read_bytes()).hexdigest()
    study.dump(manifest_path, manifest)
    with pytest.raises(ModelError):
        study.run(cases, manifest_path, tmp_path / "out", ABC)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("mutation", ["missing-stratum", "wrong-count", "tampered-dataset"])
def test_manifest_consistency_controls(tmp_path, mutation):
    cases, path, manifest = inputs(tmp_path)
    if mutation == "missing-stratum":
        manifest["seeds"].append(18)
    elif mutation == "wrong-count":
        manifest["cases"] = 2
    else:
        manifest["dataset_sha256"] = "0" * 64
    study.dump(path, manifest)
    with pytest.raises(ModelError):
        study.load_inputs(cases, path)


def test_input_certificate_detects_wrong_parallel_or_and_processor_domain(tmp_path):
    optional_backends()
    spec = toy()
    gl = domain.model(spec)
    bad = GLModel(
        gl.num_processors, gl.vertices, tuple(Edge(e.id, e.u, e.v, FALSE) for e in gl.edges)
    )
    result = domain.input_certificate(spec, bad, tmp_path / "bad.smt2", 2000)
    assert result["status"] == "COUNTEREXAMPLE" and len(result["witness"]) == 4
    with pytest.raises(ModelError, match="processor domain"):
        domain.input_certificate(
            spec, GLModel(5, gl.vertices, gl.edges), tmp_path / "domain.smt2", 2000
        )
    invalid = deepcopy(spec)
    invalid["links"][0]["processors"] = [0]
    with pytest.raises(ModelError):
        domain.model(invalid)


def test_unknown_keeps_output_and_samples_without_becoming_a_proof(tmp_path, monkeypatch):
    optional_backends()
    _, _, manifest = inputs(tmp_path / "inputs")
    monkeypatch.setattr(
        study, "check", lambda *a, **kw: {"status": "UNKNOWN", "reason": "development control"}
    )
    output = tmp_path / "unknown"
    row = study.worker(toy(), manifest, "chain-sift", output, ABC)
    assert row["status"] == "UNCERTIFIED"
    assert row["certificate"]["reason"] == "development control"
    assert row["exhaustive_states"] == 16
    assert (output / "output.json").exists() and not study.certified(row)


@pytest.mark.parametrize("backend", ["direct-sift", "chain-sift"])
def test_compile_cli_exact_gate_portable_evaluation_reliability_and_no_overwrite(tmp_path, backend):
    optional_backends()
    original, output = tmp_path / "model.json", tmp_path / "compiled.json"
    study.dump(original, domain.model(toy()).to_dict())
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    command = [
        sys.executable,
        "-m",
        "faultgraph.chainstudy",
        "compile",
        str(original),
        "--backend",
        backend,
        "--output",
        str(output),
    ]
    run = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=30)
    assert run.returncode == 0, run.stderr + run.stdout
    assert json.loads(run.stdout)["status"] == "UNSAT_FINITE_EQUIVALENCE"
    assert all(
        load(output).evaluate(s) == domain.oracle(toy(), s) for s in product((0, 1), repeat=4)
    )
    evaluate = subprocess.run(
        [sys.executable, "-m", "faultgraph.symbolic", "evaluate", str(output), "--state", "1111"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    assert evaluate.returncode == 0 and json.loads(evaluate.stdout)["operational"]
    ps = tmp_path / "probabilities.json"
    study.dump(ps, [0.9] * 4)
    probability = subprocess.run(
        [
            sys.executable,
            "-m",
            "faultgraph.symbolic",
            "reliability",
            str(output),
            "--probabilities",
            str(ps),
            "--common-cause",
            "0.1",
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    value = json.loads(probability.stdout)
    assert probability.returncode == 0
    exact = sum(
        0.9 ** sum(s) * 0.1 ** (4 - sum(s))
        for s in product((0, 1), repeat=4)
        if domain.oracle(toy(), s)
    )
    assert value["independent"] == pytest.approx(exact)
    assert value["correlated"] == pytest.approx(0.9 * exact)
    before = output.read_bytes()
    again = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=30)
    assert again.returncode == 2 and output.read_bytes() == before


def test_compile_unknown_only_writes_candidate(tmp_path, monkeypatch):
    optional_backends()
    from faultgraph.symbolic import equivalence

    original, output = tmp_path / "model.json", tmp_path / "compiled.json"
    study.dump(original, domain.model(toy()).to_dict())
    monkeypatch.setattr(
        equivalence,
        "check",
        lambda *a, **kw: {"status": "UNKNOWN", "reason": "development control"},
    )
    assert compile_model(original, "chain-sift", output, 1000)["status"] == "UNKNOWN"
    assert not output.exists()
    assert Path(str(output) + ".candidate.json").exists()
    assert Path(str(output) + ".certificate.json").exists()


def test_encoding_wall_deadline_cannot_become_a_certificate(monkeypatch):
    def interrupted():
        raise TimeoutError("development encoding timeout")

    row = study.proof_query(interrupted, 1000)
    assert row["status"] == "UNKNOWN" and row["wall_limit_ms"] == 1000
    moments = iter((1.0, 3.0))
    monkeypatch.setattr(study, "perf_counter", lambda: next(moments))
    row = study.proof_query(lambda: {"status": "UNSAT_FINITE_EQUIVALENCE"}, 1000)
    assert row["status"] == "UNKNOWN" and row["wall_ms"] == 2000
    assert row["late_result"]["status"] == "UNSAT_FINITE_EQUIVALENCE"


def test_study_summary_propagates_pairing_failure(tmp_path, monkeypatch):
    optional_backends()
    if not ABC.is_file():
        pytest.skip("real pinned ABC binary not installed")
    cases, manifest, _ = inputs(tmp_path / "inputs")
    original_analyze = study.analyze

    def mismatch_before_analysis(output):
        path = Path(output) / "raw_runs.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["truth_sha256"] = "0" * 64
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return original_analyze(output)

    monkeypatch.setattr(study, "analyze", mismatch_before_analysis)
    summary = study.run(cases, manifest, tmp_path / "study", ABC)
    assert summary["failures"] == 0  # certificates alone would have passed
    assert summary["status"] == "INCOMPLETE" and not summary["analysis_complete"]
    assert summary["evidence_errors"]


@pytest.mark.parametrize("status", ["COUNTEREXAMPLE", "ENCODING_ERROR"])
def test_late_negative_evidence_remains_a_failure(status, monkeypatch):
    moments = iter((1.0, 3.0))
    monkeypatch.setattr(study, "perf_counter", lambda: next(moments))
    row = study.proof_query(lambda: {"status": status, "witness": "010"}, 1000)
    assert row["status"] == status and row["witness"] == "010"
    assert row["late"] and row["wall_limit_exceeded"]
