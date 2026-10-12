"""Six prospective native mechanism families, with independent domain semantics.

Structured engineering models with synthetic parameter instantiations, not field
deployments. Every graph vertex is a required port/role; processors control native
links or multiway buses. No critical-predicate plus unit-tree wrappers.
"""

import random
from itertools import combinations

from ..expr import Not, Var, conj, disj
from ..model import ConditionedModel, Edge, GLModel
from ..transform import combine_aligned, combine_wedge

FAMILIES = (
    "multiway_bus",
    "quorum_wheel",
    "replicated_endpoint_ladder",
    "reserve_release_mobius",
    "rendezvous_bipartite",
    "weighted_capacity_blocks",
)


def topology(family):
    if family == "multiway_bus":
        groups = [(0, 1, 2), (2, 3, 4), (4, 5, 6), (6, 7, 0)]
        return sorted({tuple(sorted(p)) for g in groups for p in combinations(g, 2)})
    if family == "quorum_wheel":
        return sorted(
            [(0, i) for i in range(1, 8)] + [(i, 1 if i == 7 else i + 1) for i in range(1, 8)]
        )
    if family == "replicated_endpoint_ladder":
        return (
            [(i, i + 1) for i in range(3)]
            + [(i, i + 1) for i in range(4, 7)]
            + [(i, i + 4) for i in range(4)]
        )
    if family == "reserve_release_mobius":
        return [(i, (i + 1) % 8) for i in range(8)] + [(i, i + 4) for i in range(4)]
    if family == "rendezvous_bipartite":
        return [(i, j) for i in range(4) for j in range(4, 8)]
    if family == "weighted_capacity_blocks":
        return (
            list(combinations(range(4), 2))
            + list(combinations(range(4, 8), 2))
            + [(i, i + 4) for i in range(4)]
        )
    raise ValueError("unknown native family")


def generate(family, n, seed):
    if family not in FAMILIES or n not in (6, 8, 10, 12):
        raise ValueError("outside preregistered generator domain")
    rng = random.Random(900000 + FAMILIES.index(family) * 10000 + n * 100 + seed)
    modes = []
    for mode in (0, 1):

        def variables(start, count):
            return rng.sample(list(range(1, n)), count)

        endpoint_roles = {i: variables(i, 2) for i in range(8)}
        if family == "multiway_bus":
            records = [
                {"ports": list(g), "kind": "any", "vars": variables(j * 2, 2)}
                for j, g in enumerate(((0, 1, 2), (2, 3, 4), (4, 5, 6), (6, 7, 0)))
            ]
        else:
            records = []
            for j, pair in enumerate(topology(family)):
                kind = {
                    "quorum_wheel": "quorum",
                    "replicated_endpoint_ladder": "endpoints",
                    "reserve_release_mobius": "reserve",
                    "rendezvous_bipartite": "rendezvous",
                    "weighted_capacity_blocks": "capacity",
                }[family]
                count = 3 if kind in ("quorum", "reserve") else 4
                record = {"ports": list(pair), "kind": kind, "vars": variables(j, count)}
                if kind == "endpoints":
                    record["vars"] = (
                        endpoint_roles[pair[0]] + endpoint_roles[pair[1]] + variables(j, 2)
                    )
                if kind == "capacity":
                    record.update(weights=[1, 2, 3, 4], demand=5 + (j + mode) % 2)
                records.append(record)
        modes.append(records)
    # Ensure declared processor variables occur syntactically without selecting
    # cases according to optimizer results or operational labels.
    counts = {i: sum(r["vars"].count(i) for mode in modes for r in mode) for i in range(1, n)}
    for missing in [i for i, count in counts.items() if count == 0]:
        options = [
            (r, j)
            for mode in modes
            for r in mode
            for j, v in enumerate(r["vars"])
            if counts[v] > 1 and missing not in r["vars"] and (r["kind"] != "endpoints" or j >= 4)
        ]
        if options:
            r, j = rng.choice(options)
            counts[r["vars"][j]] -= 1
            r["vars"][j] = missing
            counts[missing] += 1
    return {
        "id": f"{family}-n{n}-s{seed}",
        "family": family,
        "n": n,
        "seed": seed,
        "vertices": list(range(8)),
        "selector_processor": n,
        "modes": modes,
        "interpretation": "idealized native mechanism, synthetic role allocation",
    }


def rule_expression(rule):
    x = [Var(i) for i in rule["vars"]]
    kind = rule["kind"]
    if kind == "any":
        return disj(*x)
    if kind == "quorum":
        return disj(*(conj(*p) for p in combinations(x, 2)))
    if kind == "endpoints":
        return conj(disj(*x[:2]), disj(*x[2:4]), disj(*x[4:]))
    if kind == "reserve":
        return disj(x[0], conj(Not(x[1]), x[2]))
    if kind == "rendezvous":
        return disj(conj(*x[:2]), conj(*x[2:]))
    if kind == "capacity":
        winning = []
        for mask in range(1 << len(x)):
            subset = [i for i in range(len(x)) if mask & (1 << i)]
            total = sum(rule["weights"][i] for i in subset)
            if total >= rule["demand"] and all(
                total - rule["weights"][i] < rule["demand"] for i in subset
            ):
                winning.append(conj(*(x[i] for i in subset)))
        return disj(*winning)
    raise ValueError("unknown rule")


def auxiliaries(spec):
    models = []
    for mode in spec["modes"]:
        pairs = {}
        for rule in mode:
            f = rule_expression(rule)
            for pair in combinations(sorted(rule["ports"]), 2):
                pairs.setdefault(pair, []).append(f)
        models.append(
            GLModel(
                spec["n"],
                tuple(map(str, spec["vertices"])),
                tuple(
                    Edge(f"e{i}", str(a), str(b), disj(*fs))
                    for i, ((a, b), fs) in enumerate(sorted(pairs.items()))
                ),
                spec["id"] + ":aux",
            )
        )
    selector = Var(spec["selector_processor"])
    return ConditionedModel((Not(selector), selector), tuple(models))


def published(spec):
    return combine_aligned(auxiliaries(spec)).model


def naive(spec):
    return combine_wedge(auxiliaries(spec))


def domain_oracle(spec, state):
    """Imperative resource rules + partition merging; never consumes GL/AST data."""
    mode = spec["modes"][state[spec["selector_processor"] - 1]]
    components = [{v} for v in spec["vertices"]]
    for rule in mode:
        values = [state[i - 1] for i in rule["vars"]]
        kind = rule["kind"]
        if kind == "any":
            active = sum(values) > 0
        elif kind == "quorum":
            active = sum(values) >= 2
        elif kind == "endpoints":
            active = sum(values[:2]) > 0 and sum(values[2:4]) > 0 and sum(values[4:]) > 0
        elif kind == "reserve":
            active = values[0] == 1 or (values[1] == 0 and values[2] == 1)
        elif kind == "rendezvous":
            active = values[0] * values[1] + values[2] * values[3] > 0
        elif kind == "capacity":
            active = (
                sum(w * v for w, v in zip(rule["weights"], values, strict=True)) >= rule["demand"]
            )
        else:
            raise ValueError("unknown independent domain rule")
        if active:
            ports = set(rule["ports"])
            touching = [c for c in components if c & ports]
            joined = set().union(*touching)
            components = [c for c in components if not c & ports] + [joined]
    return len(components) == 1
