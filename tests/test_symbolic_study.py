import json
from itertools import product
from pathlib import Path

import pytest

from faultgraph.model import ModelError
from faultgraph.symbolic.__main__ import load
from faultgraph.symbolic.compile import connectivity_circuit
from faultgraph.symbolic.cudd import Compiled
from faultgraph.symbolic.native import model, oracle
from faultgraph.symbolic.study import ARMS, analyze, input_certificate, worker


def spec(policy="single"):
    return {
        "id": "development-triangle",
        "family": "toy",
        "seed": 1,
        "n": 3,
        "policy": policy,
        "vertices": ["a", "b", "c"],
        "links": [
            {"u": "a", "v": "b", "processors": [1] if policy == "single" else [1, 2]},
            {"u": "b", "v": "c", "processors": [2] if policy == "single" else [2, 3]},
            {"u": "a", "v": "c", "processors": [3] if policy == "single" else [1, 3]},
        ],
    }


@pytest.mark.parametrize("policy", ["single", "dual", "shared"])
def test_independent_policy_oracle_and_input_certificate(policy, tmp_path):
    pytest.importorskip("z3")
    data = spec(policy)
    g = model(data)
    c = connectivity_circuit(g, factor=True)
    assert all(c.evaluate(s) == oracle(data, s) for s in product((0, 1), repeat=3))
    assert input_certificate(data, g, tmp_path, 1000)["status"] == "UNSAT_PREDICATE_EQUIVALENCE"
    wrong = {**data, "policy": "dual" if policy != "dual" else "shared"}
    if policy != "single":
        assert input_certificate(wrong, g, tmp_path, 1000)["status"] == "COUNTEREXAMPLE"


def test_actual_worker_all_arms_on_development_only(tmp_path):
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")
    binary = Path("work/v3/abc/abc")
    if not binary.is_file():
        pytest.skip("ABC external tool absent")
    manifest = {"construction_seconds": 30, "verification_ms": 3000, "samples": 8, "repeats": 1}
    for arm in ARMS:
        r = worker(spec(), manifest, arm, tmp_path / arm, binary)
        assert r["status"] == "COMPLETE", (arm, r)
        assert r["exhaustive_states"] == 8 and r["sampled_checks"] == 0
        assert r["certificate"]["status"] == "UNSAT_FINITE_EQUIVALENCE"


def test_incomplete_results_cannot_support_hypothesis(tmp_path):
    manifest = {"families": ["toy"], "seeds": [1], "bootstrap_seed": 1, "bootstrap_replicates": 100}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "cases.json").write_text(json.dumps([spec()]))
    (tmp_path / "raw_runs.jsonl").write_text("")
    assert analyze(tmp_path)["status"] == "INCONCLUSIVE"
    # Even apparently winning candidate/reference pairs omit required comparators.
    rows = []
    for arm in ("block-sift", "cudd-sift"):
        rows.append(
            dict(
                case=spec()["id"],
                arm=arm,
                status="COMPLETE",
                construction_ms=1 if arm == "block-sift" else 5,
                peak_rss_bytes=100,
                metrics={"bdd_nodes": 1},
                timing={"uniform": {"p50_ms": 1}},
            )
        )
    (tmp_path / "raw_runs.jsonl").write_text("\n".join(map(json.dumps, rows)))
    assert analyze(tmp_path)["status"] == "INCONCLUSIVE"


def test_artifact_rejects_nonobject(tmp_path):
    p = tmp_path / "input.json"
    p.write_text("[]")
    with pytest.raises(ModelError):
        load(p)


def test_shared_blocks_do_not_multiply_correlated_probabilities():
    pytest.importorskip("dd.cudd")
    from faultgraph.expr import Var
    from faultgraph.model import Edge, GLModel

    g = GLModel(16, ("a", "b", "c"), (Edge("a", "a", "b", Var(1)), Edge("b", "b", "c", Var(1))))
    d = Compiled(connectivity_circuit(g, factor=True)).diagram
    assert d.reliability([0.7] * 16) == pytest.approx(0.7)
    assert d.reliability([0.7] * 16) != pytest.approx(0.49)
