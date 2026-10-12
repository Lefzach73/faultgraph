"""Deliberate bad controls: demonstrate detection, never silently fix witnesses."""

import networkx as nx

from faultgraph.construct import model_for_domain
from faultgraph.equivalence import check_functions, check_models
from faultgraph.evaluator import active_edges, operational
from faultgraph.expr import FALSE, TRUE, Var
from faultgraph.model import Edge, GLModel
from faultgraph.oracle import domain_truth, threshold
from faultgraph.reliability import exact
from faultgraph.transform import split_vertex


def test_inverted_polarity_control():
    m = model_for_domain({"kind": "threshold", "n": 3, "required": 2})
    r = check_functions(
        3, lambda s: operational(m, tuple(1 - x for x in s)), lambda s: threshold(s, 2)
    )
    assert r.status == "COUNTEREXAMPLE" and r.witness == "000"


def test_zero_edge_activation_control():
    m = GLModel(1, ("a", "b"), (Edge("zero", "a", "b", FALSE),))
    assert check_functions(1, lambda _: True, lambda s: operational(m, s)).witness == "0"


def test_dropped_isolated_vertex_control():
    m = GLModel(1, ("a", "b", "c"), (Edge("e", "a", "b", TRUE),))

    def bad(s):
        g = nx.Graph()
        g.add_edges_from((e.u, e.v) for e in active_edges(m, s))
        return nx.is_connected(g)

    assert check_functions(1, bad, lambda s: operational(m, s)).status == "COUNTEREXAMPLE"


def test_directed_connectivity_control():
    m = GLModel(1, ("a", "b"), (Edge("e", "b", "a", TRUE),))
    g = nx.DiGraph()
    g.add_nodes_from(m.vertices)
    g.add_edge("b", "a")
    assert (
        check_functions(
            1, lambda _: nx.is_strongly_connected(g), lambda s: operational(m, s)
        ).status
        == "COUNTEREXAMPLE"
    )


def test_broken_split_unit_control():
    m = GLModel(1, ("a", "b"), (Edge("e", "a", "b", Var(1)),))
    good = split_vertex(m, "a", "new", ["e"], "bridge").model
    bad = GLModel(
        1,
        good.vertices,
        tuple(Edge(e.id, e.u, e.v, FALSE if e.id == "bridge" else e.predicate) for e in good.edges),
    )
    assert check_models(m, bad).witness == "1"


def test_failure_count_only_control_nonbasic():
    spec = {"kind": "line", "n": 4, "k": 2}
    assert domain_truth(spec, (1, 1, 0, 0)) != domain_truth(spec, (1, 0, 1, 0))
    r = check_functions(4, lambda s: threshold(s, 2), lambda s: domain_truth(spec, s))
    assert r.status == "COUNTEREXAMPLE"


def test_equal_reliability_cannot_certify_equivalence():
    a = GLModel(2, ("a", "b"), (Edge("e", "a", "b", Var(1)),))
    b = GLModel(2, ("a", "b"), (Edge("e", "a", "b", Var(2)),))
    assert exact(2, lambda s: operational(a, s), [0.5, 0.5]) == exact(
        2, lambda s: operational(b, s), [0.5, 0.5]
    )
    assert check_models(a, b).witness == "01"
