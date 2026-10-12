"""Processor relabeling with an explicit old-index -> new-index bijection."""

from .expr import Const, Not, Var
from .model import Edge, GLModel, ModelError


def permute_processors(model, mapping):
    n = model.num_processors
    if (
        type(mapping) is not tuple
        or any(type(i) is not int for i in mapping)
        or set(mapping) != set(range(1, n + 1))
        or len(mapping) != n
    ):
        raise ModelError("permutation must be a bijection of one-based processor indices")

    def rewrite(e):
        if isinstance(e, Const):
            return e
        if isinstance(e, Var):
            return Var(mapping[e.index - 1])
        if isinstance(e, Not):
            return Not(rewrite(e.arg))
        return type(e)(tuple(rewrite(a) for a in e.args))

    return GLModel(
        n,
        model.vertices,
        tuple(Edge(e.id, e.u, e.v, rewrite(e.predicate)) for e in model.edges),
        model.model_id + "-permuted",
        dict(model.metadata),
    )


def permute_state(state, mapping):
    result = [0] * len(state)
    for old, new in enumerate(mapping):
        result[new - 1] = state[old]
    return tuple(result)
