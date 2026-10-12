from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from faultgraph.construct import model_for_domain
from faultgraph.equivalence import check_functions, check_models
from faultgraph.evaluator import conditioned_operational, operational
from faultgraph.expr import FALSE, TRUE, And, Not, Or, Var, simplify
from faultgraph.model import ConditionedModel, Edge, GLModel, ModelError
from faultgraph.transform import (
    add_leaf,
    align_models,
    combine_aligned,
    combine_wedge,
    split_vertex,
    subdivide,
    zero_edge,
)


@pytest.mark.parametrize("n", range(1, 13))
def test_t0_t3_exact_domains(n):
    m = model_for_domain({"n": n, "kind": "threshold", "required": max(1, n - 1)})
    ts = [
        zero_edge(m, "v0", "v2", "zero"),
        add_leaf(m, "v0", "new", "unit"),
        split_vertex(m, "v1", "split", ["e1"], "bridge"),
        subdivide(m, "e0", "sub", "unit"),
    ]
    for t in ts:
        assert check_models(m, t.model).status == "EXHAUSTIVE_PASS"
        assert t.record["before_hash"] == m.digest
        assert t.record["after_hash"] == t.model.digest
        assert t.record["check_status"] == "NOT_CHECKED"  # no automatic proof claim


def test_t4_arbitrary_structure_and_index_alignment():
    a = GLModel(3, ("a", "b"), (Edge("e", "a", "b", Var(2)),))
    b = GLModel(3, ("q", "r", "s"), (Edge("z", "q", "r", Var(3)), Edge("y", "r", "s", TRUE)))
    cm = ConditionedModel((Var(1), Not(Var(1))), (a, b))
    with pytest.raises(ModelError, match="alignment"):
        combine_aligned(cm)
    aligned = align_models((a, b))
    for original, t in zip((a, b), aligned, strict=False):
        assert check_models(original, t.model).status == "EXHAUSTIVE_PASS"
    c = combine_aligned(ConditionedModel(cm.selectors, tuple(t.model for t in aligned))).model
    w = combine_wedge(cm)
    for m in (c, w):
        assert (
            check_functions(
                3, lambda s, m=m: operational(m, s), lambda s: conditioned_operational(cm, s)
            ).status
            == "EXHAUSTIVE_PASS"
        )
    # same vertices and IDs, incorrect incidence map must also reject
    bad = GLModel(
        3,
        c.vertices,
        tuple(
            Edge(e.id, c.vertices[1], c.vertices[2], e.predicate) if i == 0 else e
            for i, e in enumerate(c.edges)
        ),
    )
    with pytest.raises(ModelError):
        combine_aligned(ConditionedModel((Var(1), Not(Var(1))), (c, bad)))


def test_invalid_split_and_disconnected_published_alignment():
    m = GLModel(1, ("a", "b", "c"), (Edge("e", "a", "b", Var(1)),))
    with pytest.raises(ModelError):
        split_vertex(m, "a", "d", ["unknown"], "unit")
    with pytest.raises(ModelError):
        split_vertex(m, "a", "d", ["e", "e"], "unit")
    with pytest.raises(ModelError, match="connected underlying"):
        align_models((m,))


EXPRS = st.recursive(
    st.sampled_from([Var(1), Var(2), Var(3), TRUE, FALSE]),
    lambda children: st.one_of(
        children.map(Not),
        st.tuples(children, children).map(And),
        st.tuples(children, children).map(Or),
    ),
    max_leaves=10,
)


@given(EXPRS, EXPRS, EXPRS)
@settings(max_examples=60, derandomize=True)
def test_generated_graph_transform_and_simplifier(a, b, c):
    m = GLModel(
        3,
        ("a", "b", "c"),
        (Edge("ab", "a", "b", a), Edge("bc", "b", "c", b), Edge("ac", "a", "c", c)),
    )
    transformed = split_vertex(m, "a", "new", ["ac"], "bridge").model
    assert check_models(m, transformed).status == "EXHAUSTIVE_PASS"
    for e in (a, b, c):
        assert all(e.evaluate(s) == simplify(e).evaluate(s) for s in product((0, 1), repeat=3))


class TransformSequence(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.original = GLModel(3, ("a", "b"), (Edge("e", "a", "b", Var(1)),))
        self.current = self.original
        self.counter = 0

    @rule()
    def leaf(self):
        self.counter += 1
        self.current = add_leaf(
            self.current, self.current.vertices[-1], f"v{self.counter}", f"u{self.counter}"
        ).model

    @rule()
    def subdivision(self):
        self.counter += 1
        self.current = subdivide(self.current, "e", f"v{self.counter}", f"u{self.counter}").model

    @invariant()
    def exact_truth_preserved(self):
        assert check_models(self.original, self.current).status == "EXHAUSTIVE_PASS"


TestTransformSequence = TransformSequence.TestCase
TestTransformSequence.settings = settings(max_examples=25, stateful_step_count=12, derandomize=True)


def json_truth(data, state):
    """Independent interpreter for the test reference grammar, not AST methods."""
    kind = data["type"]
    if kind == "const":
        return data["value"]
    if kind == "var":
        return state[data["index"] - 1] == 1
    if kind == "not":
        return not json_truth(data["arg"], state)
    values = [json_truth(a, state) for a in data["args"]]
    return all(values) if kind == "and" else any(values)


@given(EXPRS)
@settings(max_examples=80, derandomize=True)
def test_independent_expression_interpreter(e):
    for s in product((0, 1), repeat=3):
        assert e.evaluate(s) == json_truth(e.to_dict(), s)


def test_processor_permutation_inverse_state_mapping():
    from faultgraph.permute import permute_processors, permute_state

    model = GLModel(3, ("a", "b"), (Edge("e", "a", "b", And((Var(1), Not(Var(2))))),))
    mapping = (3, 1, 2)
    relabeled = permute_processors(model, mapping)
    assert all(
        operational(model, s) == operational(relabeled, permute_state(s, mapping))
        for s in product((0, 1), repeat=3)
    )
    with pytest.raises(ModelError):
        permute_processors(model, (1, 1, 2))
