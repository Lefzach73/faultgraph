"""IJEM 2026 Props 2–6 and Eq (2), with explicit lineage.

The T0–T4 names are handoff labels, not names assigned by the authors.
"""

from dataclasses import dataclass
from time import perf_counter

from .evaluator import connected
from .expr import FALSE, TRUE, Not, conj, disj
from .model import Edge, GLModel, ModelError


@dataclass(frozen=True)
class Transformation:
    model: GLModel
    record: dict


def record(before, after, name, vertices, edges, start, obligation):
    return Transformation(
        after,
        {
            "transform": name,
            "before_hash": before.digest,
            "after_hash": after.digest,
            "vertex_lineage": vertices,
            "edge_lineage": edges,
            "elapsed_ms": (perf_counter() - start) * 1000,
            "obligations": obligation,
            "check_status": "NOT_CHECKED",
            "attribution": "Romankevich et al., IJEM 2026, §4",
        },
    )


def replace(model, vertices=None, edges=None, suffix="transformed"):
    return GLModel(
        model.num_processors,
        model.vertices if vertices is None else tuple(vertices),
        model.edges if edges is None else tuple(edges),
        model.model_id + "-" + suffix,
        dict(model.metadata),
    )


def identities(model):
    return {v: [v] for v in model.vertices}, {e.id: [e.id] for e in model.edges}


def zero_edge(model, u, v, edge_id):
    start = perf_counter()
    after = replace(model, edges=(*model.edges, Edge(edge_id, u, v, FALSE)), suffix="T0")
    vs, es = identities(model)
    return record(model, after, "T0", vs, es, start, ["added predicate identically zero"])


def split_vertex(model, vertex, new_vertex, moved_edge_ids, bridge_id):
    start = perf_counter()
    if vertex not in model.vertices or new_vertex in model.vertices:
        raise ModelError("split requires an existing vertex and a fresh vertex")
    incident = {e.id for e in model.edges if vertex in (e.u, e.v)}
    if len(set(moved_edge_ids)) != len(moved_edge_ids) or not set(moved_edge_ids) <= incident:
        raise ModelError("split incidence mapping must contain unique incident edge IDs only")
    edges = [
        Edge(
            e.id,
            new_vertex if e.u == vertex and e.id in moved_edge_ids else e.u,
            new_vertex if e.v == vertex and e.id in moved_edge_ids else e.v,
            e.predicate,
        )
        for e in model.edges
    ]
    edges.append(Edge(bridge_id, vertex, new_vertex, TRUE))
    after = replace(model, (*model.vertices, new_vertex), edges, "T1")
    vs, es = identities(model)
    vs[vertex] = [vertex, new_vertex]
    return record(
        model,
        after,
        "T1",
        vs,
        es,
        start,
        ["every original incidence assigned exactly once", "split bridge identically one"],
    )


def add_leaf(model, parent, vertex, edge_id):
    start = perf_counter()
    if parent not in model.vertices or vertex in model.vertices:
        raise ModelError("leaf requires existing parent and fresh vertex")
    after = replace(
        model, (*model.vertices, vertex), (*model.edges, Edge(edge_id, parent, vertex, TRUE)), "T2"
    )
    vs, es = identities(model)
    return record(model, after, "T2", vs, es, start, ["leaf attaching predicate identically one"])


def subdivide(model, edge_id, vertex, new_edge_id):
    start = perf_counter()
    if vertex in model.vertices or edge_id not in {e.id for e in model.edges}:
        raise ModelError("subdivision requires existing edge and fresh vertex")
    edges = []
    for e in model.edges:
        if e.id == edge_id:
            edges.extend(
                (Edge(e.id, e.u, vertex, e.predicate), Edge(new_edge_id, vertex, e.v, TRUE))
            )
        else:
            edges.append(e)
    after = replace(model, (*model.vertices, vertex), edges, "T3")
    vs, es = identities(model)
    es[edge_id] = [edge_id, new_edge_id]
    return record(
        model,
        after,
        "T3",
        vs,
        es,
        start,
        ["subdivision predicates equal original f and constant one"],
    )


def combine_aligned(conditioned):
    start = perf_counter()
    first = conditioned.models[0]
    if any(m.topology != first.topology for m in conditioned.models):
        raise ModelError("Eq (2) requires identical vertices, edge IDs AND endpoint alignment")
    maps = [{e.id: e for e in m.edges} for m in conditioned.models]
    edges = tuple(
        Edge(
            e.id,
            e.u,
            e.v,
            disj(
                *(
                    conj(c, em[e.id].predicate)
                    for c, em in zip(conditioned.selectors, maps, strict=False)
                )
            ),
        )
        for e in first.edges
    )
    after = GLModel(
        first.num_processors, first.vertices, edges, "combined", {"source": "IJEM 2026 Eq (2)"}
    )
    return Transformation(
        after,
        {
            "transform": "T4-combine",
            "before_hashes": [m.digest for m in conditioned.models],
            "after_hash": after.digest,
            "elapsed_ms": (perf_counter() - start) * 1000,
            "vertex_lineage": [{v: [v] for v in m.vertices} for m in conditioned.models],
            "edge_lineage": [{e.id: [e.id] for e in m.edges} for m in conditioned.models],
            "obligations": ["selectors exact partition", "all graph/edge incidences aligned"],
            "check_status": "NOT_CHECKED",
            "attribution": "Romankevich et al., IJEM 2026 Eq (2)",
        },
    )


def tree_edge_ids(model):
    if not connected(model.vertices, model.edges):
        raise ModelError(
            "published alignment and wedge construction require connected underlying graphs"
        )
    seen, selected = {model.vertices[0]}, set()
    while len(seen) < len(model.vertices):
        for e in model.edges:
            if (e.u in seen) != (e.v in seen):
                seen.update((e.u, e.v))
                selected.add(e.id)
                break
    return selected


def align_models(models):
    """Prop 6 root-merging construction: attach other graphs' unit trees.

    Each original graph retains its own predicates, every other graph's
    spanning tree has unit predicates and its remaining edges zero predicates.
    This is a constructive baseline, not the paper's compact manual alignment.
    """
    if not models or any(m.num_processors != models[0].num_processors for m in models):
        raise ModelError("nonempty list of matching processor domains required")
    maps = [
        {v: "root" if j == 0 else f"m{i}:v{j}" for j, v in enumerate(m.vertices)}
        for i, m in enumerate(models)
    ]
    trees = [tree_edge_ids(m) for m in models]
    vertices = tuple(dict.fromkeys(v for mp in maps for v in mp.values()))
    results = []
    for own, model in enumerate(models):
        start = perf_counter()
        edges = [
            Edge(
                f"m{i}:e{j}",
                maps[i][e.u],
                maps[i][e.v],
                e.predicate if own == i else TRUE if e.id in trees[i] else FALSE,
            )
            for i, m in enumerate(models)
            for j, e in enumerate(m.edges)
        ]
        after = GLModel(model.num_processors, vertices, tuple(edges), f"aligned-{own}")
        es = {e.id: [f"m{own}:e{j}"] for j, e in enumerate(model.edges)}
        results.append(
            record(
                model,
                after,
                "T4-align",
                {v: [maps[own][v]] for v in model.vertices},
                es,
                start,
                ["unit spanning trees attach new vertices", "other new edges zero"],
            )
        )
    return tuple(results)


def combine_wedge(conditioned):
    """HAIT 2026 Eq (1): f OR NOT selector, graphs joined at one root."""
    aligned = align_models(conditioned.models)
    base = aligned[0].model
    edges = []
    for i, (m, c) in enumerate(zip(conditioned.models, conditioned.selectors, strict=False)):
        own_edges = [e for e in aligned[i].model.edges if e.id.startswith(f"m{i}:")]
        edges.extend(
            Edge(a.id, a.u, a.v, disj(e.predicate, Not(c)))
            for e, a in zip(m.edges, own_edges, strict=False)
        )
    return GLModel(
        base.num_processors,
        base.vertices,
        tuple(edges),
        "hait-wedge",
        {"source": "Romankevich et al., HAIT 2026 Eq (1)"},
    )
