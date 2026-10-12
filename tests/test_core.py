import csv
from itertools import product
from pathlib import Path

import networkx as nx
import pytest

from faultgraph.construct import model_for_domain
from faultgraph.equivalence import check_functions, check_models
from faultgraph.evaluator import active_edges, operational
from faultgraph.expr import FALSE, TRUE, And, Not, Or, Var, complexity, parse_expr, simplify
from faultgraph.model import (
    ConditionedModel,
    Edge,
    GLModel,
    ModelError,
    load_json,
    load_model,
    model_from_dict,
)
from faultgraph.oracle import domain_truth, threshold

ROOT = Path(__file__).resolve().parents[1]


def triangle():
    return load_model(ROOT / "examples/triangle_2of3.model.json")


def test_triangle_all_states_and_networkx():
    m = triangle()
    rows = list(csv.DictReader((ROOT / "examples/triangle_2of3.expected.csv").open()))
    assert len(rows) == 8
    for row in rows:
        assert operational(m, row["state_x1x2x3"]) == bool(int(row["operational"]))
    for s in product((0, 1), repeat=3):
        g = nx.Graph()
        g.add_nodes_from(m.vertices)
        g.add_edges_from((e.u, e.v) for e in active_edges(m, s))
        assert operational(m, s) == nx.is_connected(g) == threshold(s, 2)
    assert sum(operational(m, s) for s in product((0, 1), repeat=3)) == 4


@pytest.mark.parametrize(
    "d",
    [
        {"type": "python", "code": "__import__('os').system('false')"},
        {"type": "var", "name": "x0"},
        {"type": "var", "index": 0},
        {"type": "var", "index": True},
        {"type": "var", "index": 4},
        {"type": "var", "name": "x1()"},
        {"type": "const", "value": 1},
        {"type": "const", "value": "true"},
        {"type": "not", "arg": {"type": "const", "value": False}, "extra": 0},
        {"type": "and", "args": []},
        {"type": "or", "args": [{"type": "var", "index": 1}]},
        "x1 or x2",
        None,
        [],
        {"type": "var", "index": 1, "name": "x1"},
    ],
)
def test_safe_input_rejected(d):
    with pytest.raises(ValueError):
        parse_expr(d, 3)


def test_ast_limits_and_roundtrip():
    e = Or((Var(1), And((Var(2), Not(Var(3))))))
    assert parse_expr(e.to_dict(), 3) == e
    d = {"type": "var", "index": 1}
    for _ in range(65):
        d = {"type": "not", "arg": d}
    with pytest.raises(ValueError, match="limit"):
        parse_expr(d, 3)
    with pytest.raises(ValueError, match="limit"):
        parse_expr(e.to_dict(), 3, max_nodes=2)


def test_singleton_and_isolated_vertices():
    assert operational(GLModel(1, ("v",), ()), "0")
    assert not operational(GLModel(1, ("a", "b"), ()), "1")
    m = GLModel(1, ("a", "b", "isolated"), (Edge("e", "a", "b", TRUE),))
    assert not operational(m, "1")


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "duplicate_vertex",
        "endpoint",
        "selfloop",
        "parallel",
        "duplicate_edge",
        "float_n",
        "bool_n",
        "domain",
        "extra",
    ],
)
def test_model_schema_validation(mutation):
    d = triangle().to_dict()
    if mutation == "empty":
        d["vertices"] = []
    elif mutation == "duplicate_vertex":
        d["vertices"].append("A")
    elif mutation == "endpoint":
        d["edges"][0]["u"] = "missing"
    elif mutation == "selfloop":
        d["edges"][0]["v"] = "A"
    elif mutation == "parallel":
        d["edges"].append({**d["edges"][0], "id": "parallel", "u": "B", "v": "A"})
    elif mutation == "duplicate_edge":
        d["edges"][1]["id"] = d["edges"][0]["id"]
    elif mutation == "float_n":
        d["num_processors"] = 3.0
    elif mutation == "bool_n":
        d["num_processors"] = True
    elif mutation == "domain":
        d["edges"][0]["predicate"] = {"type": "var", "index": 4}
    elif mutation == "extra":
        d["arbitrary_code"] = "print(1)"
    with pytest.raises(ValueError):
        model_from_dict(d)


@pytest.mark.parametrize("state", ["11", "1111", "112", [True, 1, 1], [1.0, 1, 1], [1, -1, 1]])
def test_state_validation(state):
    with pytest.raises(ValueError):
        operational(triangle(), state)


def test_duplicate_json_fields(tmp_path):
    p = tmp_path / "d.json"
    p.write_text('{"schema_version":"faultgraph-1","schema_version":"bad"}')
    with pytest.raises(ModelError, match="duplicate"):
        load_json(p)
    p.write_text('{"x":NaN}')
    with pytest.raises(ModelError, match="nonfinite"):
        load_json(p)


def test_condition_partition_witnesses():
    m = GLModel(2, ("a", "b"), (Edge("e", "a", "b", Var(1)),))
    assert ConditionedModel((Var(1), Not(Var(1))), (m, m))
    with pytest.raises(ModelError, match="witness=00"):
        ConditionedModel((Var(1), Var(2)), (m, m))
    with pytest.raises(ModelError, match="matches=2"):
        ConditionedModel((TRUE, TRUE), (m, m))
    with pytest.raises(ModelError):
        ConditionedModel((TRUE,), (GLModel(13, ("a",), ()),))


@pytest.mark.parametrize("n", range(1, 13))
def test_threshold_independent_oracle_exhaustively(n):
    spec = {"kind": "threshold", "n": n, "required": max(0, n - 2)}
    m = model_for_domain(spec)
    r = check_functions(n, lambda s: operational(m, s), lambda s: domain_truth(spec, s))
    assert r.status == "EXHAUSTIVE_PASS" and r.checked_states == 2**n


def test_complexity_method_and_simplification():
    raw = Or((Var(1), Var(1), And((Var(1), Var(2))), FALSE))
    assert complexity(raw)["total"] == 4
    assert simplify(raw) == Var(1)
    assert complexity(simplify(raw))["total"] == 0
    assert simplify(And((Var(1), Not(Var(1))))) == FALSE
    assert simplify(Or((Var(1), Not(Var(1))))) == TRUE


def test_status_is_not_general_proof():
    m = GLModel(13, ("a",), ())
    assert check_models(m, m).status == "NOT_CHECKED"
    assert check_models(triangle(), triangle()).scope.startswith("exhaustive finite")


def test_model_metadata_immutable_and_detached():
    metadata = {"nested": {"values": [1, 2]}}
    model = GLModel(1, ("a",), (), metadata=metadata)
    digest = model.digest
    metadata["nested"]["values"].append(3)
    assert model.digest == digest
    with pytest.raises(TypeError):
        model.metadata["nested"]["values"] = ()
    exported = model.to_dict()
    exported["metadata"]["nested"]["values"].append(4)
    assert model.digest == digest
