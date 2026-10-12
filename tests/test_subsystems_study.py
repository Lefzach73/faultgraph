import json
from itertools import product

import pytest

from faultgraph.cli import main
from faultgraph.experiments import run_study, weighted
from faultgraph.expr import Not, Var
from faultgraph.model import load_conditioned
from faultgraph.paper import source_models
from faultgraph.reliability import exact
from faultgraph.subsystems import count_oracle, donor_resources, reproduce_donors, source_donor


@pytest.mark.parametrize("n", [5, 8])
def test_published_donor_interface_exhaustive(n):
    _, g, h, m = source_donor(n)
    for s in product((0, 1), repeat=n):
        r = donor_resources(s)
        expected, count = count_oracle(s, m)
        assert r["kappa"] == expected
        assert sum(r["available"]) == count
        if not expected:
            assert all(not e.evaluate(s) for e in g)


def test_reproduce_donor_artifacts(tmp_path):
    r = reproduce_donors(tmp_path)
    assert r["checked_states"] == 288 and r["mismatches"] == 0


def test_weighted_probability_endpoint_regression():
    domain = list(product((0, 1), repeat=12))
    assert 0 <= weighted([(s, True) for s in domain], [0.99] * 12) <= 1
    assert 0 <= exact(12, lambda _: True, [0.99] * 12) <= 1


def test_frozen_dataset_tamper_rejected(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"dataset": "data.json", "dataset_sha256": "wrong"}))
    (tmp_path / "data.json").write_text("[]")
    with pytest.raises(ValueError, match="hash mismatch"):
        run_study(p, tmp_path / "out")


def test_offline_compose_and_optimize_commands(tmp_path, capsys):
    models, _ = source_models()
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": "faultgraph-conditioned-1",
                "selectors": [Var(1).to_dict(), Not(Var(1)).to_dict()],
                "models": [models["K1-prime"].to_dict(), models["K2-prime"].to_dict()],
            }
        )
    )
    assert len(load_conditioned(p).models) == 2
    out = tmp_path / "combined.json"
    assert main(["compose", str(p), "--output", str(out)]) == 0
    assert main(["optimize", str(out), "--output", str(tmp_path / "optimized.json")]) == 0
    assert main(["compose", str(p), "--method", "aligned", "--output", str(out)]) == 2
