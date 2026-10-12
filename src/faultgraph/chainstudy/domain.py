"""Physical parallel links retained in domain truth, OR-grouped in the GL graph."""

from collections import defaultdict
from pathlib import Path
from time import perf_counter

from faultgraph.expr import Var, conj, disj
from faultgraph.model import Edge, GLModel, ModelError
from faultgraph.symbolic.equivalence import graph_formula
from faultgraph.symbolic.native import oracle

__all__ = ["model", "input_certificate", "oracle", "validate"]


def validate(spec):
    """Validate the physical domain before grouping; retain parallel links."""
    if type(spec) is not dict or spec.get("policy") not in ("single", "dual", "shared"):
        raise ModelError("unknown physical link policy")
    n, vertices, links = spec.get("n"), spec.get("vertices"), spec.get("links")
    if type(n) is not int or not 1 <= n <= 64:
        raise ModelError("physical domain requires 1<=n<=64")
    if (
        type(vertices) is not list
        or not 1 <= len(vertices) <= 128
        or any(type(v) is not str or not v for v in vertices)
        or len(set(vertices)) != len(vertices)
        or type(links) is not list
    ):
        raise ModelError("invalid physical topology")
    for link in links:
        if type(link) is not dict:
            raise ModelError("invalid physical link")
        processors = link.get("processors")
        if (
            link.get("u") not in vertices
            or link.get("v") not in vertices
            or link["u"] == link["v"]
            or type(processors) is not list
            or len(processors) != (1 if spec["policy"] == "single" else 2)
            or any(type(i) is not int or not 1 <= i <= n for i in processors)
        ):
            raise ModelError("invalid physical endpoints or controller indices")


def model(spec):
    validate(spec)
    if spec["policy"] not in ("single", "dual", "shared"):
        raise ModelError("unknown policy")
    groups = defaultdict(list)
    for link in spec["links"]:
        variables = [Var(i) for i in link["processors"]]
        if len(variables) != (1 if spec["policy"] == "single" else 2):
            raise ModelError("wrong controller count")
        predicate = disj(*variables) if spec["policy"] == "dual" else conj(*variables)
        groups[tuple(sorted((link["u"], link["v"])))].append(predicate)
    return GLModel(
        spec["n"],
        tuple(spec["vertices"]),
        tuple(
            Edge(f"e{i}", u, v, disj(*functions))
            for i, ((u, v), functions) in enumerate(sorted(groups.items()))
        ),
        spec["id"],
        {
            "source_file": spec.get("source_file"),
            "scope": spec.get("scope"),
            "physical_links": len(spec["links"]),
            "parallel_semantics": "OR of ready physical links",
        },
    )


def input_certificate(spec, gl, path, timeout_ms):
    import z3

    validate(spec)
    if type(timeout_ms) is not int or timeout_ms < 1:
        raise ModelError("certificate timeout must be positive")
    if spec["n"] != gl.num_processors:
        raise ModelError("source processor domain changed")
    if tuple(spec["vertices"]) != gl.vertices:
        raise ModelError("source vertices changed")
    groups = defaultdict(list)
    variables = [z3.Bool(f"x{i}") for i in range(1, spec["n"] + 1)]
    for link in spec["links"]:
        count = z3.Sum([z3.If(variables[i - 1], 1, 0) for i in link["processors"]])
        groups[tuple(sorted((link["u"], link["v"])))].append(
            count >= (2 if spec["policy"] == "shared" else 1)
        )
    if set(groups) != {tuple(sorted((e.u, e.v))) for e in gl.edges}:
        raise ModelError("source endpoint pairs changed")
    differences = []
    for edge in gl.edges:
        pair = tuple(sorted((edge.u, edge.v)))
        local = GLModel(spec["n"], ("a", "b"), (Edge("e", "a", "b", edge.predicate),))
        differences.append(z3.Xor(graph_formula(local, variables), z3.Or(*groups[pair])))
    solver = z3.Solver()
    solver.set(timeout=timeout_ms, random_seed=0)
    solver.add(z3.Or(*differences))
    Path(path).write_text(solver.to_smt2())
    start = perf_counter()
    answer = solver.check()
    result = {
        "status": "UNSAT_PREDICATE_EQUIVALENCE"
        if answer == z3.unsat
        else "COUNTEREXAMPLE"
        if answer == z3.sat
        else "UNKNOWN",
        "seconds": perf_counter() - start,
        "solver": z3.get_version_string(),
        "timeout_ms": timeout_ms,
        "reason": solver.reason_unknown() if answer == z3.unknown else None,
        "physical_edges": len(spec["links"]),
        "logical_edges": len(gl.edges),
        "topology_match": True,
        "scope": "all physical-link rules and OR grouping equivalent for every original processor assignment",
    }
    if answer == z3.sat:
        result["witness"] = "".join(
            str(int(z3.is_true(solver.model().eval(v, model_completion=True)))) for v in variables
        )
    return result
