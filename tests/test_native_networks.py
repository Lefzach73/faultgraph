from itertools import product

import pytest

from faultgraph.construct import model_for_domain
from faultgraph.evaluator import operational
from faultgraph.optimize import optimize
from faultgraph.oracle import domain_truth


@pytest.mark.parametrize(
    "channels",
    [
        [(0, 1), (1, 2), (2, 3), (0, 3)],
        [(0, 1), (0, 2), (0, 3), (1, 2)],
        [(0, 1), (1, 2), (2, 3), (0, 2)],
    ],
)
def test_independent_cutsets_vs_gl_network(channels):
    spec = {"kind": "channels", "n": 4, "vertices": 4, "channels": channels}
    model = model_for_domain(spec)
    assert all(operational(model, s) == domain_truth(spec, s) for s in product((0, 1), repeat=4))
    r = optimize(model)
    assert r["attempts"] == 0 and r["model"].digest == model.digest
