from itertools import product

import pytest

from faultgraph.chainstudy import domain
from faultgraph.evaluator import operational
from faultgraph.symbolic.native import oracle


@pytest.mark.parametrize("policy", ["single", "dual", "shared"])
def test_parallel_physical_edges_preserve_independent_oracle(policy, tmp_path):
    pytest.importorskip("z3")
    data = {
        "id": "parallel-test",
        "policy": policy,
        "n": 4,
        "vertices": ["a", "b", "c"],
        "links": [
            {"u": "a", "v": "b", "processors": [1] if policy == "single" else [1, 2]},
            {"u": "a", "v": "b", "processors": [3] if policy == "single" else [3, 4]},
            {"u": "b", "v": "c", "processors": [2] if policy == "single" else [2, 4]},
            {"u": "a", "v": "c", "processors": [4] if policy == "single" else [1, 4]},
        ],
    }
    gl = domain.model(data)
    assert len(gl.edges) == 3 and len(data["links"]) == 4
    assert all(operational(gl, state) == oracle(data, state) for state in product((0, 1), repeat=4))
    assert (
        domain.input_certificate(data, gl, tmp_path / "input.smt2", 2000)["status"]
        == "UNSAT_PREDICATE_EQUIVALENCE"
    )
