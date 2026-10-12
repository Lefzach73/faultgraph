"""Cut-guarded elimination candidate, predeclared in research/v2/CANDIDATE_SPEC.md.

Known building blocks; research priority is unestablished. Every accepted step has
an exact finite certificate. Independent domain truth is never passed to search.
"""

from itertools import combinations
from time import perf_counter

from ..expr import FALSE, conj, disj, simplify
from ..metrics import model_metrics
from ..model import Edge, GLModel, ModelError
from ..optimize import expression_only
from .kernel import Program, expression_mask, finite_certificate, structural_key


def costs(model):
    m = model_metrics(model)
    return (m["vertices"], m["edges"], m["total"], Program.build(model).dag_ops)


def eliminate(model, vertex, *, guard="cut"):
    if model.num_processors > 12 or len(model.vertices) > 12:
        raise ModelError("outside bounded implementation envelope: n<=12 and V<=12")
    if vertex not in model.vertices or len(model.vertices) < 3:
        raise ModelError(
            "elimination requires an existing vertex and at least two remaining vertices"
        )
    if guard not in ("cut", "global", "unsafe-none"):
        raise ModelError("unknown guard policy")
    remaining = tuple(v for v in model.vertices if v != vertex)
    neighbor = {}
    pairs = {}
    for e in model.edges:
        if vertex == e.u:
            neighbor[e.v] = e.predicate
        elif vertex == e.v:
            neighbor[e.u] = e.predicate
        else:
            pairs[tuple(sorted((e.u, e.v)))] = e.predicate
    g = simplify(disj(*neighbor.values()))
    for u, v in combinations(sorted(neighbor), 2):
        key = (u, v)
        pairs[key] = simplify(disj(pairs.get(key, FALSE), conj(neighbor[u], neighbor[v])))
    cache = {}
    gm = expression_mask(g, model.num_processors, cache)
    implies = {
        pair: (expression_mask(f, model.num_processors, cache) & ~gm) == 0
        for pair, f in pairs.items()
    }
    selected = None
    crossing = set()
    if guard == "global":
        crossing = set(pairs)  # conventional blanket obligation placement
    elif guard == "cut":
        options = []
        for mask in range((1 << (len(remaining) - 1)) - 1):
            side = {remaining[0]} | {v for j, v in enumerate(remaining[1:]) if mask & (1 << j)}
            edges = {p for p in pairs if (p[0] in side) != (p[1] in side)}
            options.append(
                (sum(not implies[p] for p in edges), len(side), tuple(sorted(side)), edges)
            )
        _, _, selected, crossing = min(options, key=lambda a: a[:3])
    edges = []
    guarded = []
    discharged = []
    for i, (pair, f) in enumerate(sorted(pairs.items())):
        # Global baseline uses all-edge guarding; cut candidate discharges implications.
        if pair in crossing:
            if guard == "cut" and implies[pair]:
                discharged.append(pair)
            else:
                f = simplify(conj(g, f))
                guarded.append(pair)
        edges.append(Edge(f"e{i}", *pair, f))
    after = GLModel(
        model.num_processors,
        remaining,
        tuple(edges),
        model.model_id + ":eliminate:" + vertex,
        {"method": "guarded-elimination-v2", "source_model": model.digest},
    )
    # Incident predicates contribute both fill and global obligation.
    edge_lineage = {
        e.id: [
            a.id for a in after.edges if vertex in (e.u, e.v) or set((a.u, a.v)) == set((e.u, e.v))
        ]
        for e in model.edges
    }
    record = {
        "removed_vertex": vertex,
        "guard_policy": guard,
        "guard": g.to_dict(),
        "cut": list(selected) if selected else None,
        "guarded_pairs": guarded,
        "discharged_pairs": discharged,
        "vertex_lineage": {v: [] if v == vertex else [v] for v in model.vertices},
        "edge_lineage": edge_lineage,
        "obligations": [
            "two or more remaining vertices",
            "fill for every incident pair",
            "non-isolation obligation enforced on a proper cut or every edge",
            "guard omission only after exact implication",
        ],
    }
    return after, record


def dominated(a, b):
    return all(x <= y for x, y in zip(a, b, strict=True)) and a != b


def frontier(models):
    scored = [(m, costs(m)) for m in models]
    return [
        m for m, a in scored if not any(dominated(b, a) for other, b in scored if other is not m)
    ]


def minfill_order(model):
    pairs = {frozenset((e.u, e.v)) for e in model.edges}

    def score(v):
        ns = {e.v if e.u == v else e.u for e in model.edges if v in (e.u, e.v)}
        return sum(frozenset(p) not in pairs for p in combinations(ns, 2)), len(ns), v

    return sorted(model.vertices, key=score)


def search(model, *, strategy="beam-cut", budget=24, beam_width=3, seconds=30):
    if model.num_processors > 12 or len(model.vertices) > 12:
        return {"status": "NOT_CHECKED", "model": model, "records": [], "frontier": [model]}
    if strategy not in ("beam-cut", "greedy-cut", "greedy-global"):
        raise ValueError("unknown search strategy")
    start = perf_counter()
    initial = expression_only(model)
    initial_cost = costs(initial)
    archive = [initial]
    beam = [initial]
    seen = {structural_key(initial)}
    records = []
    attempts = 0
    timeout = False
    while beam and attempts < budget:
        children = []
        for parent in beam:
            if len(parent.vertices) < 3:
                continue
            for vertex in minfill_order(parent):
                if attempts >= budget:
                    break
                if perf_counter() - start > seconds:
                    timeout = True
                    break
                attempts += 1
                try:
                    after, lineage = eliminate(
                        parent, vertex, guard="global" if strategy == "greedy-global" else "cut"
                    )
                    c = costs(after)
                    allowed = c[2] <= 2 * initial_cost[2] + 32 and c[3] <= 2 * initial_cost[3] + 16
                    cert = finite_certificate(parent, after)
                    accepted = cert["status"] == "EXHAUSTIVE_PASS" and allowed
                    records.append(
                        {
                            **lineage,
                            "certificate": cert,
                            "costs": c,
                            "accepted": accepted,
                            "rejection": None
                            if accepted
                            else "BUDGET"
                            if not allowed
                            else cert["status"],
                        }
                    )
                    if accepted and structural_key(after) not in seen:
                        seen.add(structural_key(after))
                        children.append(after)
                        archive.append(after)
                        if strategy.startswith("greedy"):
                            break
                except (ValueError, RecursionError) as error:
                    records.append(
                        {
                            "removed_vertex": vertex,
                            "accepted": False,
                            "rejection": "RESOURCE_OR_LEGALITY_LIMIT",
                            "message": str(error),
                        }
                    )
            if timeout:
                break
        if not children or timeout:
            break
        ordered = sorted(
            frontier(children),
            key=lambda m: (costs(m)[0], costs(m)[1], costs(m)[3], costs(m)[2], structural_key(m)),
        )
        beam = ordered[:beam_width] if strategy == "beam-cut" else ordered[:1]
    pf = frontier(archive)
    chosen = min(
        pf, key=lambda m: (costs(m)[0], costs(m)[1], costs(m)[3], costs(m)[2], structural_key(m))
    )
    return {
        "status": "TIMEOUT" if timeout else "EXHAUSTIVE_PASS",
        "model": chosen,
        "records": records,
        "frontier": pf,
        "attempts": attempts,
        "elapsed_seconds": perf_counter() - start,
        "certificate": finite_certificate(model, chosen),
        "budget": budget,
        "selection": "V,E,DAG-ops,tree-ops; no runtime tuning",
    }


def prune_edges(model, budget=24, seconds=30):
    start = perf_counter()
    current = expression_only(model)
    records = []
    for e in tuple(current.edges)[:budget]:
        if perf_counter() - start > seconds:
            return {"status": "TIMEOUT", "model": current, "records": records}
        after = GLModel(
            current.num_processors,
            current.vertices,
            tuple(a for a in current.edges if a.id != e.id),
            current.model_id + ":prune",
            dict(current.metadata),
        )
        certificate = finite_certificate(current, after)
        records.append(
            {
                "edge": e.id,
                "certificate": certificate,
                "accepted": certificate["status"] == "EXHAUSTIVE_PASS",
            }
        )
        if records[-1]["accepted"]:
            current = after
    return {
        "status": "EXHAUSTIVE_PASS",
        "model": current,
        "records": records,
        "certificate": finite_certificate(model, current),
    }
