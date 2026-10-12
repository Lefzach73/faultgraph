import json
import os
import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest

from faultgraph.bdd import BDD
from faultgraph.construct import model_for_domain
from faultgraph.equivalence import check_models
from faultgraph.evaluator import operational
from faultgraph.expr import FALSE, TRUE, Or, Var
from faultgraph.metrics import model_metrics
from faultgraph.model import Edge, GLModel, ModelError, save_model
from faultgraph.optimize import contract_unit, optimize
from faultgraph.paper import ACCEPTED, B1, B2, PUBLISHED, oracle, reproduce, source_models
from faultgraph.reliability import binomial

ROOT = Path(__file__).resolve().parents[1]


def test_all_paper_models_and_published_counts():
    models, _ = source_models()
    assert len(ACCEPTED) == len(set(ACCEPTED)) == 22
    assert set(B1) | set(B2) == set(ACCEPTED) and not set(B1) & set(B2)
    for name in ("K12", "K12-prime", "K12-composed", "M", "M-prime", "M-unsimplified"):
        assert all(operational(models[name], s) == oracle(s) for s in product((0, 1), repeat=8))
    for name, pub in PUBLISHED.items():
        assert {k: model_metrics(models[name])[k] for k in pub} == pub
    assert sum(oracle(s) for s in product((0, 1), repeat=8)) == 59


def test_reproduction_missing_source_and_bad_spec(tmp_path):
    with pytest.raises(ModelError, match="BLOCKED"):
        reproduce(tmp_path, tmp_path / "out")
    p = tmp_path / "reproduction.json"
    p.write_text('{"model":"missing.json"}')
    with pytest.raises(ModelError, match="BLOCKED"):
        reproduce(ROOT, tmp_path / "out", p)


def test_optimizer_unit_parallel_and_zero_lineage():
    m = GLModel(
        2,
        ("a", "b", "c"),
        (Edge("unit", "a", "b", TRUE), Edge("e1", "a", "c", Var(1)), Edge("e2", "b", "c", Var(2))),
    )
    after, record = contract_unit(m, "unit")
    assert after.edges[0].predicate == Or((Var(1), Var(2)))
    assert check_models(m, after).status == "EXHAUSTIVE_PASS"
    assert record["edge_lineage"]["unit"] == []
    assert record["edge_lineage"]["e1"] == record["edge_lineage"]["e2"]
    with pytest.raises(ModelError):
        contract_unit(m, "e1")
    zero = GLModel(2, ("a", "b"), (Edge("zero", "a", "b", FALSE),))
    r = optimize(zero)
    assert r["status"] == "EXHAUSTIVE_PASS" and not r["model"].edges
    # Connected singleton only reached by contraction when source always works.
    r = optimize(GLModel(1, ("a", "b"), (Edge("unit", "a", "b", TRUE),)))
    assert len(r["model"].vertices) == 1


@pytest.mark.parametrize("n", range(1, 9))
def test_bdd_truth_and_reliability(n):
    for k in (0, 1, n):
        m = model_for_domain({"kind": "threshold", "n": n, "required": k})
        b = BDD.from_indicator(n, lambda s, m=m: operational(m, s))
        assert all(b.evaluate(s) == (sum(s) >= k) for s in product((0, 1), repeat=n))
        assert b.reliability([0.8] * n) == pytest.approx(binomial(n, k, 0.8))
        assert b == BDD.from_indicator(n, lambda s, k=k: sum(s) >= k)


def cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "faultgraph", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )


def test_cli_vertical_slices_and_exit_codes(tmp_path):
    model = ROOT / "examples/triangle_2of3.model.json"
    assert cli("validate", model).returncode == 0
    r = cli("evaluate", model, "--state", "110")
    assert r.returncode == 0 and json.loads(r.stdout)["operational"] is True
    assert cli("evaluate", model, "--state", "11x").returncode == 2
    assert cli("prove-equivalence", model, model).returncode == 0
    bad = tmp_path / "bad.json"
    save_model(GLModel(3, ("a",), ()), bad)
    r = cli("prove-equivalence", model, bad)
    assert r.returncode == 1 and json.loads(r.stdout)["witness"] == "000"
    ps = tmp_path / "p.json"
    ps.write_text("[0.9,0.9,0.9]")
    r = cli("reliability", model, "--probabilities", ps, "--samples", 100, "--seed", 17)
    assert r.returncode == 0 and json.loads(r.stdout)["exact"] == pytest.approx(0.972)
    out = tmp_path / "leaf.json"
    assert cli("transform", model, "--operation", "T2", "--u", "A", "--output", out).returncode == 0
    assert out.exists() and Path(str(out) + ".lineage.json").exists()
    assert cli("prove-equivalence", model, out).returncode == 0
    dot = tmp_path / "model.dot"
    assert cli("export-dot", model, "--state", "000", "--output", dot).returncode == 0
    assert '"A";' in dot.read_text() and "dashed" in dot.read_text()
    r = cli("reproduce-paper", "--output", tmp_path / "paper")
    assert r.returncode == 0 and json.loads(r.stdout)["mismatch_count"] == 0
