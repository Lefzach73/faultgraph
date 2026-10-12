"""Transparent design-reference constructions, distinct from published fixtures."""

from itertools import combinations

from .expr import FALSE, TRUE, Not, Var, conj, disj
from .model import ConditionedModel, Edge, GLModel
from .transform import align_models, combine_aligned


def threshold_expr(n, required):
    if not 0 <= required <= n:
        raise ValueError("invalid threshold")
    return disj(
        *(conj(*(Var(i) for i in group)) for group in combinations(range(1, n + 1), required))
    )


def graph_for_predicate(n, predicate, shape="path", size=4):
    vertices = tuple(f"v{i}" for i in range(size))
    if shape == "single":
        return GLModel(n, ("v0",), (), "single")
    pairs = (
        [(i, i + 1) for i in range(size - 1)]
        if shape == "path"
        else [(0, i) for i in range(1, size)]
    )
    edges = tuple(
        Edge(f"e{j}", vertices[u], vertices[v], predicate if j == 0 else TRUE)
        for j, (u, v) in enumerate(pairs)
    )
    return GLModel(n, vertices, edges, "domain-design-reference")


def model_for_domain(spec):
    n, kind = spec["n"], spec["kind"]
    if kind == "threshold":
        f = threshold_expr(n, spec["required"])
    elif kind in ("line", "ring"):
        k = spec["k"]
        f = disj(
            *(
                conj(*(Var((i + j) % n + 1) for j in range(k)))
                for i in range(n if kind == "ring" else n - k + 1)
            )
        )
    elif kind == "exceptional":
        extra = disj(
            *(
                conj(*(Var(i + 1) if x == "1" else Not(Var(i + 1)) for i, x in enumerate(s)))
                for s in spec["accepted"]
            )
        )
        f = disj(threshold_expr(n, n - spec["max_failures"]), extra)
    elif kind == "conditional":
        a = graph_for_predicate(n, threshold_expr(n, spec["high"]), "path", 3)
        b = graph_for_predicate(n, threshold_expr(n, spec["low"]), "star", 4)
        aligned = align_models((a, b))
        return combine_aligned(
            ConditionedModel((Var(1), Not(Var(1))), tuple(t.model for t in aligned))
        ).model
    elif kind == "paired":
        # Each bridge expresses survival of an independently required processor pair.
        vertices = tuple(f"v{i}" for i in range(n // 2 + 1))
        return GLModel(
            n,
            vertices,
            tuple(
                Edge(
                    f"e{i // 2}",
                    vertices[i // 2],
                    vertices[i // 2 + 1],
                    disj(Var(i + 1), Var(i + 2)),
                )
                for i in range(0, n, 2)
            ),
            "paired",
        )
    elif kind == "corner":
        return graph_for_predicate(n, TRUE if spec["operational"] else FALSE, size=3)
    elif kind == "channels":
        vertices = tuple(f"c{i}" for i in range(spec["vertices"]))
        return GLModel(
            n,
            vertices,
            tuple(
                Edge(f"p{i + 1}", vertices[a], vertices[b], Var(i + 1))
                for i, (a, b) in enumerate(spec["channels"])
            ),
            "native-channel-network",
        )
    else:
        raise ValueError("unknown domain family")
    return graph_for_predicate(n, f, spec.get("shape", "path"), spec.get("size", 4))
