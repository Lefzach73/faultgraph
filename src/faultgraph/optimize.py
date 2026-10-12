"""Bounded conservative candidate; no novelty or global optimality claim.

Constant-edge contraction is prior art (HAIT 2026 Example 1). Every returned
candidate is independently checked against its source on the full finite domain.
"""

from time import perf_counter

from .equivalence import check_models
from .expr import FALSE, TRUE, disj, simplify
from .metrics import model_metrics
from .model import Edge, ModelError
from .transform import identities, replace


def contract_unit(model, edge_id):
    edge = next((e for e in model.edges if e.id == edge_id), None)
    if edge is None or edge.predicate != TRUE:
        raise ModelError("contraction requires a literal constant-one edge")
    keep, remove = edge.u, edge.v
    mapping = {v: keep if v == remove else v for v in model.vertices}
    groups = {}
    for e in model.edges:
        u, v = mapping[e.u], mapping[e.v]
        if u == v:
            continue
        key = frozenset((u, v))
        groups.setdefault(key, []).append((e, u, v))
    edges = []
    lineage = {}
    for group in groups.values():
        first, u, v = group[0]
        edges.append(Edge(first.id, u, v, disj(*(e.predicate for e, _, _ in group))))
        for e, _, _ in group:
            lineage[e.id] = [first.id]
    for e in model.edges:
        lineage.setdefault(e.id, [])
    after = replace(model, [v for v in model.vertices if v != remove], edges, "contract")
    return after, {
        "vertex_lineage": {v: [mapping[v]] for v in model.vertices},
        "edge_lineage": lineage,
        "rule": "constant-one contraction; parallel predicates OR; internal loops discarded",
    }


def expression_only(model):
    return replace(
        model,
        edges=[Edge(e.id, e.u, e.v, simplify(e.predicate)) for e in model.edges],
        suffix="local-v1",
    )


def objective(model):
    m = model_metrics(model)
    return m["vertices"], m["edges"], m["total"]


def optimize(model, budget=32, *, topology=True, expressions=True):
    if type(budget) is not int or budget < 1 or budget > 256:
        raise ValueError("budget must be an integer in 1..256")
    if model.num_processors > 12:
        return {"status": "NOT_CHECKED", "model": model, "records": [], "attempts": 0}
    start = perf_counter()
    current, records, attempts = model, [], 0
    while attempts < budget:
        proposals = []
        if expressions:
            proposed = expression_only(current)
            if any(
                a.predicate != b.predicate
                for a, b in zip(current.edges, proposed.edges, strict=False)
            ):
                vs, es = identities(current)
                proposals.append(
                    (proposed, {"rule": "local-v1", "vertex_lineage": vs, "edge_lineage": es})
                )
        if topology:
            if any(e.predicate == FALSE for e in current.edges):
                after = replace(
                    current,
                    edges=[e for e in current.edges if e.predicate != FALSE],
                    suffix="remove-zero",
                )
                vs, es = identities(current)
                es = {e.id: [] if e.predicate == FALSE else [e.id] for e in current.edges}
                proposals.append(
                    (
                        after,
                        {
                            "rule": "remove literal zero edges",
                            "vertex_lineage": vs,
                            "edge_lineage": es,
                        },
                    )
                )
            unit = next((e for e in current.edges if e.predicate == TRUE), None)
            if unit:
                proposals.append(contract_unit(current, unit.id))
        accepted = False
        for after, lineage in proposals:
            if attempts >= budget:
                break
            attempts += 1
            check = check_models(current, after)
            before_metrics, after_metrics = model_metrics(current), model_metrics(after)
            improving = (
                after_metrics["total"] <= before_metrics["total"]
                and all(a <= b for a, b in zip(objective(after), objective(current), strict=False))
                and objective(after) != objective(current)
            )
            record = {
                **lineage,
                "before_hash": current.digest,
                "after_hash": after.digest,
                "certificate": check.to_dict(),
                "accepted": check.status == "EXHAUSTIVE_PASS" and improving,
            }
            records.append(record)
            if record["accepted"]:
                current = after
                accepted = True
                break
        if not accepted:
            break
    check = check_models(model, current)
    return {
        "status": check.status,
        "model": current,
        "records": records,
        "attempts": attempts,
        "certificate": check.to_dict(),
        "elapsed_ms": (perf_counter() - start) * 1000,
        "objective": "Pareto non-worsening V,E,tree-ops; no runtime selection",
    }


def pareto(models):
    objs = {name: objective(m) for name, m in models.items()}
    return [
        name
        for name, a in objs.items()
        if not any(
            all(x <= y for x, y in zip(b, a, strict=False)) and b != a
            for other, b in objs.items()
            if other != name
        )
    ]
