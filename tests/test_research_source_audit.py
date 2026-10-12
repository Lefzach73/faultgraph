from itertools import product

import pytest

from faultgraph.evaluator import operational
from faultgraph.expr import Var
from faultgraph.research.source_audit import (
    cycle,
    hait9_models,
    hait9_oracle,
    mle_functions,
    z3_connected,
)


def test_hait9_independent_oracle():
    for model in hait9_models().values():
        assert all(operational(model, s) == hait9_oracle(s) for s in product((0, 1), repeat=9))


def test_mle_vector_not_confused_with_singleton_graph():
    for n in range(1, 7):
        for m in range(1, n + 1):
            fs = mle_functions(m, tuple(Var(i) for i in range(1, n + 1)))
            assert len(fs) == n - m + 1
            assert all(
                sum(f.evaluate(s) for f in fs) == min(n - m + 1, sum(s))
                for s in product((0, 1), repeat=n)
            )
    with pytest.raises(ValueError):
        cycle(1, (Var(1),), "unsupported-single-cycle")


def test_z3_connectivity_encoder_against_scalar_exhaustive():
    z3 = pytest.importorskip("z3")
    model = cycle(4, mle_functions(2, tuple(Var(i) for i in range(1, 5))), "test")
    variables = z3.Bools("a b c d")
    formula = z3_connected(model, variables)
    for state in product((0, 1), repeat=4):
        value = z3.simplify(
            z3.substitute(
                formula, *[(v, z3.BoolVal(bool(s))) for v, s in zip(variables, state, strict=True)]
            )
        )
        assert z3.is_true(value) == operational(model, state)
