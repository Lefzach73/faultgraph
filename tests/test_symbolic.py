from itertools import combinations, product
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from faultgraph.evaluator import operational
from faultgraph.expr import FALSE, TRUE, And, Not, Or, Var
from faultgraph.model import Edge, GLModel, ModelError
from faultgraph.symbolic.abc import equivalence, parse_binary_aiger, synthesize
from faultgraph.symbolic.circuit import Builder, Circuit, parse_aag
from faultgraph.symbolic.compile import connectivity_circuit, edge_blocks
from faultgraph.symbolic.cudd import Compiled, Diagram
from faultgraph.symbolic.equivalence import check

EXPRESSIONS = st.recursive(
    st.sampled_from([FALSE, TRUE, Var(1), Var(2), Var(3)]),
    lambda sub: st.one_of(sub.map(Not), st.tuples(sub, sub).map(And), st.tuples(sub, sub).map(Or)),
    max_leaves=6,
)


def triangle(n=3):
    return GLModel(
        n,
        ("a", "b", "c"),
        (
            Edge("ab", "a", "b", Var(1)),
            Edge("bc", "b", "c", Var(2)),
            Edge("ac", "a", "c", Var(3)),
        ),
    )


@given(st.tuples(*[EXPRESSIONS] * 6), st.integers(0, 63))
@settings(max_examples=60, derandomize=True, deadline=None)
def test_block_and_monolithic_compilation_against_scalar_and_networkx(expressions, mask):
    import networkx as nx

    vertices = ("a", "b", "c", "d")
    pairs = tuple(combinations(vertices, 2))
    model = GLModel(
        3,
        vertices,
        tuple(
            Edge(f"e{i}", *pair, expr)
            for i, (pair, expr) in enumerate(zip(pairs, expressions, strict=True))
            if mask & (1 << i)
        ),
    )
    circuits = [connectivity_circuit(model, factor=value) for value in (False, True)]
    topology = nx.Graph()
    topology.add_nodes_from(vertices)
    topology.add_edges_from((e.u, e.v) for e in model.edges)
    blocks = edge_blocks(model)
    if nx.is_connected(topology):
        expected = {
            frozenset(frozenset(edge) for edge in block)
            for block in nx.biconnected_component_edges(topology)
        }
        assert {
            frozenset(frozenset((model.edges[i].u, model.edges[i].v)) for i in block)
            for block in blocks
        } == expected
    else:
        assert blocks is None
    for state in product((0, 1), repeat=3):
        graph = nx.Graph()
        graph.add_nodes_from(vertices)
        graph.add_edges_from((e.u, e.v) for e in model.edges if e.predicate.evaluate(state))
        assert all(
            c.evaluate(state) == operational(model, state) == nx.is_connected(graph)
            for c in circuits
        )


@pytest.mark.parametrize("n", [1, 16, 32, 64])
def test_symbolic_large_domain_exact_check_and_true_counterexample(n, tmp_path):
    pytest.importorskip("z3")
    model = GLModel(
        n,
        ("a", "b"),
        (Edge("ab", "a", "b", And(tuple(Var(i) for i in range(1, n + 1))) if n > 1 else Var(1)),),
    )
    circuit = connectivity_circuit(model, factor=True)
    result = check(model, circuit, smt_path=tmp_path / "query.smt2")
    assert result["status"] == "UNSAT_FINITE_EQUIVALENCE"
    assert (tmp_path / "query.smt2").is_file()
    bad = Circuit(circuit.n, circuit.gates, circuit.output ^ 1)
    result = check(model, bad)
    assert result["status"] == "COUNTEREXAMPLE" and result["left"] != result["right"]
    assert len(result["witness"]) == n


def test_singleton_disconnected_and_correlated_articulation():
    assert connectivity_circuit(GLModel(1, ("a",), ()), factor=True).evaluate((0,))
    assert not connectivity_circuit(GLModel(1, ("a", "b"), ()), factor=True).evaluate((1,))
    f = Or((Var(1), Var(2)))
    model = GLModel(
        2,
        ("a", "b", "c", "d", "e"),
        tuple(
            Edge(f"e{i}", u, v, f if i % 2 else Not(f))
            for i, (u, v) in enumerate(
                (("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("d", "e"), ("e", "c"))
            )
        ),
    )
    assert len(edge_blocks(model)) == 2
    circuit = connectivity_circuit(model, factor=True)
    assert all(circuit.evaluate(s) == operational(model, s) for s in product((0, 1), repeat=2))


@pytest.mark.parametrize("reorder", [False, True])
def test_real_cudd_complement_export_reliability_and_native_calls(reorder):
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")
    model = triangle()
    compiled = Compiled(connectivity_circuit(model), reorder=reorder)
    diagram = compiled.diagram
    ps = [0.2, 0.7, 0.9]
    expected = 0.0
    for state in product((0, 1), repeat=3):
        result = operational(model, state)
        assert (
            diagram.evaluate(state)
            == compiled.evaluate_native(state)
            == diagram.circuit().evaluate(state)
            == result
        )
        if result:
            weight = 1.0
            for value, p in zip(state, ps, strict=True):
                weight *= p if value else 1 - p
            expected += weight
    assert diagram.reliability(ps) == pytest.approx(expected, abs=1e-12)
    assert check(model, diagram.circuit())["status"] == "UNSAT_FINITE_EQUIVALENCE"


def test_actual_abc_and_cec(tmp_path):
    binary = Path("work/v3/abc/abc")
    if not binary.is_file():
        pytest.skip("ABC not installed; external integration explicitly not run")
    pytest.importorskip("z3")
    model = triangle()
    output, _ = synthesize(connectivity_circuit(model), binary, tmp_path / "abc")
    assert equivalence(binary, tmp_path / "abc")["status"] == "EQUIVALENT"
    assert check(model, output)["status"] == "UNSAT_FINITE_EQUIVALENCE"
    assert all(output.evaluate(s) == operational(model, s) for s in product((0, 1), repeat=3))


@pytest.mark.parametrize("value", [True, -1, 66])
def test_invalid_circuit_domain(value):
    with pytest.raises(ModelError):
        Circuit(value, (), 0)


def test_safe_serialization_and_dangling_gate_cleanup():
    builder = Builder(3)
    result = builder.land(2, 4)
    builder.land(4, 6)
    c = builder.finish(result)
    assert len(c.gates) == 1
    assert Circuit.from_dict(c.to_dict()) == c == parse_aag(c.aag(), 3)
    with pytest.raises(ModelError):
        Circuit.from_dict({**c.to_dict(), "execute": "unexpected"})
    for gates in (((4, 0),), ((True, 0),), ((-1, 0),)):
        with pytest.raises(ModelError):
            Circuit(1, gates, 0)
    with pytest.raises(ModelError):
        Diagram(1, ((0, 0, 1), (0, 0, 2)), 3)
    for data in (b"", b"aig 2 1 1 1 1\n0\n", b"aig 2 1 0 1 1\n4\n\x80"):
        with pytest.raises((ValueError, ModelError)):
            parse_binary_aiger(data, 1)


def test_no_success_on_solver_unknown(monkeypatch):
    z3 = pytest.importorskip("z3")
    real = z3.Solver

    class UnknownSolver:
        def __init__(self):
            self.inner = real()

        def set(self, **kw):
            self.inner.set(**kw)

        def add(self, *args):
            self.inner.add(*args)

        def check(self):
            return z3.unknown

        def reason_unknown(self):
            return "unit-test controlled timeout"

    monkeypatch.setattr(z3, "Solver", UnknownSolver)
    assert check(triangle(), connectivity_circuit(triangle()))["status"] == "UNKNOWN"
