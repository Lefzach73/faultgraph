"""Agent-authored development audit, independent of v4 prospective cases.

The bit-set component oracle reads an externally supplied edge activation mask;
it does not call the production AST, graph evaluator, topology plan or solver.
"""

from itertools import combinations, product
from random import Random

import pytest

from faultgraph.expr import FALSE, TRUE, And, Not, Or, Var
from faultgraph.model import Edge, GLModel
from faultgraph.symbolic.chains import NativeCompiled, topology_plan
from faultgraph.symbolic.equivalence import check


def connected_components_oracle(size, pairs, active):
    components = [1 << i for i in range(size)]
    for (u, v), enabled in zip(pairs, active, strict=True):
        if enabled:
            merged = components[u] | components[v]
            for index, component in enumerate(components):
                if component & merged:
                    components[index] = merged
    return all(component == (1 << size) - 1 for component in components)


def test_all_simple_labelled_graphs_through_five_vertices_and_all_edge_states():
    pytest.importorskip("dd.cudd")
    graph_count = assignment_count = 0
    for size in range(1, 6):
        possible = tuple(combinations(range(size), 2))
        vertices = tuple(f"v{i}" for i in range(size))
        for present in product((0, 1), repeat=len(possible)):
            pairs = tuple(pair for pair, yes in zip(possible, present, strict=True) if yes)
            n = max(1, len(pairs))
            graph = GLModel(
                n,
                vertices,
                tuple(
                    Edge(f"e{i}", vertices[u], vertices[v], Var(i + 1))
                    for i, (u, v) in enumerate(pairs)
                ),
            )
            plain = NativeCompiled(graph, compress=False).diagram
            chain = NativeCompiled(graph, compress=True).diagram
            for state in product((0, 1), repeat=n):
                truth = connected_components_oracle(size, pairs, state[: len(pairs)])
                assert plain.evaluate(state) == truth, (size, pairs, state, "plain")
                assert chain.evaluate(state) == truth, (size, pairs, state, "chain")
                assignment_count += 1
            graph_count += 1
    assert (graph_count, assignment_count) == (1099, 59814)


def test_shared_nonmonotone_rules_on_independently_generated_development_graphs():
    pytest.importorskip("dd.cudd")
    # Integer rule identifiers drive the oracle without evaluating the AST.
    expressions = (
        FALSE,
        TRUE,
        Var(1),
        Not(Var(1)),
        And((Var(1), Var(2))),
        Or((Var(2), Not(Var(3)))),
        And((Not(Var(4)), Or((Var(1), Var(3))))),
    )
    rng = Random(23011985)
    for case in range(120):
        size = 6 + case % 7
        pairs = tuple(pair for pair in combinations(range(size), 2) if rng.random() < 0.3)
        rules = tuple(rng.randrange(len(expressions)) for _ in pairs)
        vertices = tuple(f"node{i:02d}" for i in range(size))
        model = GLModel(
            4,
            vertices,
            tuple(
                Edge(f"link{i}", vertices[u], vertices[v], expressions[rule])
                for i, ((u, v), rule) in enumerate(zip(pairs, rules, strict=True))
            ),
        )
        compiled = NativeCompiled(model, compress=True)
        for state in product((0, 1), repeat=4):
            a, b, c, d = state
            values = (
                False,
                True,
                a == 1,
                a == 0,
                a + b == 2,
                b == 1 or c == 0,
                d == 0 and a + c >= 1,
            )
            truth = connected_components_oracle(size, pairs, [values[r] for r in rules])
            assert compiled.diagram.evaluate(state) == truth, (case, pairs, rules, state)


def test_shared_cycle_obligations_cannot_multiply_marginal_probabilities():
    pytest.importorskip("dd.cudd")
    # Two cycles meet at a required articulation. Each cycle operates iff x1.
    pairs = ((0, 1), (1, 2), (2, 0), (0, 3), (3, 4), (4, 0))
    vertices = tuple("abcde")
    expressions = (Var(1), Var(1), TRUE, Var(1), Var(1), TRUE)
    graph = GLModel(
        1,
        vertices,
        tuple(
            Edge(f"e{i}", vertices[u], vertices[v], expressions[i])
            for i, (u, v) in enumerate(pairs)
        ),
    )
    compiled = NativeCompiled(graph, compress=True)
    assert compiled.reduced_vertices == 1 and compiled.reduced_edges == 0
    assert len(compiled.lineage) == 2
    assert compiled.diagram.reliability([0.3]) == pytest.approx(0.3)
    assert compiled.diagram.reliability([0.3]) != pytest.approx(0.3 * 0.3)
    assert [compiled.diagram.evaluate((bit,)) for bit in (0, 1)] == [False, True]


def test_two_failed_adjacent_edges_isolate_required_vertex_despite_parallel_route():
    pytest.importorskip("dd.cudd")
    # Both outside u-v routes are active; internal vertex b is still stranded.
    pairs = ((0, 1), (1, 2), (2, 3), (0, 3), (0, 4), (4, 3))
    vertices = tuple("ubcvw")
    predicates = (Var(1), Var(2), TRUE, TRUE, TRUE, TRUE)
    graph = GLModel(
        2,
        vertices,
        tuple(
            Edge(f"e{i}", vertices[u], vertices[v], predicates[i]) for i, (u, v) in enumerate(pairs)
        ),
    )
    correct = NativeCompiled(graph, compress=True).diagram
    mutant = NativeCompiled(graph, compress=True, unsafe_drop_obligation=True).diagram
    witness = (0, 0)
    assert not connected_components_oracle(5, pairs, (0, 0, 1, 1, 1, 1))
    assert correct.evaluate(witness) is False
    assert mutant.evaluate(witness) is True


def test_mixed_closed_and_open_chains_cover_each_edge_and_ignore_input_order():
    pytest.importorskip("dd.cudd")
    pairs = ((0, 1), (1, 2), (2, 0), (0, 3), (3, 4), (4, 5), (5, 3), (3, 6))
    vertices = tuple("abcdefg")
    edges = tuple(
        Edge(f"e{i}", vertices[u], vertices[v], Var(i + 1)) for i, (u, v) in enumerate(pairs)
    )
    graph = GLModel(8, vertices, edges)
    permuted = GLModel(8, tuple(reversed(vertices)), tuple(reversed(edges)))
    root, boundaries, paths = topology_plan(graph)
    assert root == "d" and root in boundaries
    assert sorted(index for path in paths for index in path["edge_indices"]) == list(range(8))
    assert sum(path["start"] == path["end"] for path in paths) == 2
    direct = NativeCompiled(graph, compress=True).diagram
    reverse = NativeCompiled(permuted, compress=True).diagram
    for state in product((0, 1), repeat=8):
        truth = connected_components_oracle(7, pairs, state)
        assert direct.evaluate(state) == reverse.evaluate(state) == truth


def test_sixty_four_variables_and_negation_have_an_exact_instance_certificate():
    pytest.importorskip("dd.cudd")
    pytest.importorskip("z3")
    # Figure-eight topology, nine edges. Each uses seven unique inputs plus the
    # shared, negated 64th input; all 64 original variables remain in the domain.
    pairs = ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (4, 5), (5, 6), (6, 7), (7, 0))
    vertices = tuple(f"v{i}" for i in range(8))
    graph = GLModel(
        64,
        vertices,
        tuple(
            Edge(
                f"e{i}",
                vertices[u],
                vertices[v],
                And((Or(tuple(Var(j) for j in range(7 * i + 1, 7 * i + 8))), Not(Var(64)))),
            )
            for i, (u, v) in enumerate(pairs)
        ),
    )
    output = NativeCompiled(graph, compress=True).diagram
    assert check(graph, output.circuit(), timeout_ms=30000)["status"] == "UNSAT_FINITE_EQUIVALENCE"
    rng = Random(64009)
    for _ in range(64):
        state = tuple(rng.randrange(2) for _ in range(64))
        active = [sum(state[7 * i : 7 * i + 7]) > 0 and state[63] == 0 for i in range(9)]
        assert output.evaluate(state) == connected_components_oracle(8, pairs, active)
