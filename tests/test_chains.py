from itertools import combinations, product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from faultgraph.evaluator import operational
from faultgraph.expr import FALSE, TRUE, And, Not, Or, Var
from faultgraph.model import Edge, GLModel
from faultgraph.symbolic.chains import NativeCompiled, topology_plan
from faultgraph.symbolic.equivalence import check

EXP = st.recursive(
    st.sampled_from([FALSE, TRUE, Var(1), Var(2), Var(3)]),
    lambda s: st.one_of(s.map(Not), st.tuples(s, s).map(And), st.tuples(s, s).map(Or)),
    max_leaves=6,
)


@given(st.lists(EXP, min_size=7, max_size=7))
@settings(max_examples=50, derandomize=True, deadline=None)
def test_chain_compiler_shared_and_negated_predicates(expressions):
    pytest.importorskip("dd.cudd")
    pairs = (("a", "b"), ("b", "c"), ("c", "d"), ("a", "e"), ("e", "d"), ("a", "f"), ("f", "d"))
    g = GLModel(
        3,
        tuple("abcdef"),
        tuple(
            Edge(f"e{i}", *pair, predicate)
            for i, (pair, predicate) in enumerate(zip(pairs, expressions, strict=True))
        ),
    )
    outputs = [NativeCompiled(g, compress=c).diagram for c in (False, True)]
    for s in product((0, 1), repeat=3):
        expected = operational(g, s)
        assert all(d.evaluate(s) == expected for d in outputs)
    assert outputs[0].reliability([0.2, 0.7, 0.9]) == pytest.approx(
        outputs[1].reliability([0.2, 0.7, 0.9])
    )


def test_missing_obligation_has_real_witness():
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")
    g = GLModel(
        3,
        tuple("abcd"),
        (
            Edge("ab", "a", "b", Var(1)),
            Edge("bc", "b", "c", Var(2)),
            Edge("cd", "c", "d", Var(3)),
            Edge("ad", "a", "d", TRUE),
        ),
    )
    safe = NativeCompiled(g, compress=True)
    bad = NativeCompiled(g, compress=True, unsafe_drop_obligation=True)
    assert check(g, safe.diagram.circuit())["status"] == "UNSAT_FINITE_EQUIVALENCE"
    result = check(g, bad.diagram.circuit())
    assert result["status"] == "COUNTEREXAMPLE" and result["left"] != result["right"]


@pytest.mark.parametrize("nvertices", [1, 3, 4, 6, 9])
def test_cycles_singletons_and_retained_root(nvertices):
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")
    vertices = tuple(str(i) for i in range(nvertices))
    edges = (
        ()
        if nvertices == 1
        else tuple(
            Edge(f"e{i}", str(i), str((i + 1) % nvertices), Var(i % 3 + 1))
            for i in range(nvertices)
        )
    )
    g = GLModel(3, vertices, edges)
    c = NativeCompiled(g, compress=True)
    assert c.reduced_vertices == 1
    assert check(g, c.diagram.circuit())["status"] == "UNSAT_FINITE_EQUIVALENCE"
    assert all(c.diagram.evaluate(s) == operational(g, s) for s in product((0, 1), repeat=3))


def test_degree_three_control_and_disconnected_graph():
    pytest.importorskip("dd.cudd")
    vertices = tuple("abcd")
    pairs = tuple(combinations(vertices, 2))
    g = GLModel(3, vertices, tuple(Edge(f"e{i}", *p, Var(i % 3 + 1)) for i, p in enumerate(pairs)))
    c = NativeCompiled(g, compress=True)
    assert not c.lineage and c.reduced_vertices == 4 and c.reduced_edges == 6
    disconnected = GLModel(3, ("a", "b"), ())
    assert topology_plan(disconnected)[1] is None
    assert all(
        not NativeCompiled(disconnected, compress=True).diagram.evaluate(s)
        for s in product((0, 1), repeat=3)
    )


def test_all_chain_edges_covered_once_and_parallel_macros_or():
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")
    pairs = (("u", "a"), ("a", "v"), ("u", "b"), ("b", "v"), ("u", "v"))
    g = GLModel(
        3, tuple("uabv"), tuple(Edge(f"e{i}", *p, Var(i % 3 + 1)) for i, p in enumerate(pairs))
    )
    root, bounds, paths = topology_plan(g)
    assert root in bounds
    assert sorted(i for p in paths for i in p["edge_indices"]) == list(range(5))
    c = NativeCompiled(g, compress=True)
    assert c.reduced_vertices == 2 and c.reduced_edges == 1
    assert check(g, c.diagram.circuit())["status"] == "UNSAT_FINITE_EQUIVALENCE"


def test_large_correlated_chain_exact_instance():
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")
    vertices = tuple(str(i) for i in range(17))
    g = GLModel(
        64,
        vertices,
        tuple(
            Edge(
                f"e{i}",
                str(i),
                str(i + 1),
                Or((Var(4 * i + 1), And((Var(4 * i + 2), Not(Var(4 * i + 3)), Var(4 * i + 4))))),
            )
            for i in range(16)
        ),
    )
    c = NativeCompiled(g, compress=True)
    assert check(g, c.diagram.circuit(), timeout_ms=30000)["status"] == "UNSAT_FINITE_EQUIVALENCE"
