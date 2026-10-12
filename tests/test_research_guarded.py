from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from faultgraph.evaluator import operational
from faultgraph.expr import FALSE, TRUE, And, Not, Or, Var
from faultgraph.model import Edge, GLModel, ModelError
from faultgraph.research.guarded import eliminate, search
from faultgraph.research.kernel import Program, finite_certificate, truth_mask

EXP = st.recursive(
    st.sampled_from([Var(1), Var(2), Var(3), TRUE, FALSE]),
    lambda c: st.one_of(c.map(Not), st.tuples(c, c).map(And), st.tuples(c, c).map(Or)),
    max_leaves=8,
)


@given(EXP, EXP, EXP)
@settings(max_examples=60, derandomize=True)
def test_guarded_elimination_vs_independent_scalar_graph(a, b, c):
    m = GLModel(
        3,
        ("u", "v", "w"),
        (Edge("uv", "u", "v", a), Edge("vw", "v", "w", b), Edge("uw", "u", "w", c)),
    )
    p = Program.build(m)
    mask = truth_mask(m)
    for number, s in enumerate(product((0, 1), repeat=3)):
        assert p.evaluate(s) == operational(m, s) == bool(mask & (1 << number))
    for mode in ("cut", "global"):
        after, record = eliminate(m, "v", guard=mode)
        assert finite_certificate(m, after)["status"] == "EXHAUSTIVE_PASS"
        assert all(operational(m, s) == operational(after, s) for s in product((0, 1), repeat=3))
        if mode == "cut":
            assert 0 < len(record["cut"]) < len(after.vertices)


def test_missing_guard_mutant_and_singleton_boundary():
    m = GLModel(
        3,
        ("u", "v", "w"),
        (Edge("uv", "u", "v", Var(1)), Edge("vw", "v", "w", Var(2)), Edge("uw", "u", "w", Var(3))),
    )
    bad, _ = eliminate(m, "v", guard="unsafe-none")
    cert = finite_certificate(m, bad)
    assert cert["status"] == "COUNTEREXAMPLE" and cert["witness"] == "001"
    with pytest.raises(ModelError):
        eliminate(bad, "u")


def test_correlated_native_triangle_discharge():
    f = Or((Var(1), Var(2)))
    m = GLModel(
        3,
        ("a", "b", "c"),
        (Edge("ab", "a", "b", f), Edge("bc", "b", "c", f), Edge("ac", "a", "c", f)),
    )
    result = search(m, budget=24)
    assert result["certificate"]["status"] == "EXHAUSTIVE_PASS"
    assert len(result["model"].vertices) == 2
    assert any(r.get("discharged_pairs") for r in result["records"])


def test_finite_scope_and_shared_dag_operations():
    m = GLModel(13, ("a", "b"), (Edge("e", "a", "b", Var(1)),))
    assert search(m)["status"] == "NOT_CHECKED"
    with pytest.raises(ModelError):
        truth_mask(m)
    e = And((Var(1), Var(2)))
    q = GLModel(2, ("a", "b", "c"), (Edge("a", "a", "b", e), Edge("b", "b", "c", e)))
    assert Program.build(q).dag_ops == 1


@given(st.tuples(EXP, EXP, EXP, EXP, EXP, EXP))
@settings(max_examples=40, derandomize=True)
def test_four_vertex_sequences_and_dense_fill(functions):
    pairs = (("a", "b"), ("a", "c"), ("a", "d"), ("b", "c"), ("b", "d"), ("c", "d"))
    original = GLModel(
        3,
        ("a", "b", "c", "d"),
        tuple(
            Edge(f"e{i}", *pair, f)
            for i, (pair, f) in enumerate(zip(pairs, functions, strict=True))
        ),
    )
    current = original
    for vertex in ("b", "c"):
        current, _ = eliminate(current, vertex)
        for number, state in enumerate(product((0, 1), repeat=3)):
            assert (
                operational(original, state)
                == operational(current, state)
                == bool(truth_mask(current) & (1 << number))
            )
