"""Explicit hypothetical link-controller rules on archived source topologies."""

from ..expr import Var, conj, disj
from ..model import Edge, GLModel, ModelError, validate_state


def model(spec):
    policy = spec["policy"]
    if policy not in ("single", "dual", "shared"):
        raise ModelError("unknown link-controller policy")
    edges = []
    for i, link in enumerate(spec["links"]):
        xs = [Var(v) for v in link["processors"]]
        if len(xs) != (1 if policy == "single" else 2):
            raise ModelError("invalid link-controller cardinality")
        predicate = disj(*xs) if policy == "dual" else conj(*xs)
        edges.append(Edge(f"e{i}", link["u"], link["v"], predicate))
    return GLModel(
        spec["n"],
        tuple(spec["vertices"]),
        tuple(edges),
        spec["id"],
        {
            "source": spec.get("source_file"),
            "policy": policy,
            "scope": "historic topology with hypothetical processor-controlled links",
        },
    )


def oracle(spec, state):
    """Independent imperative truth: resources and set merging; no AST/GL input."""
    state = validate_state(state, spec["n"])
    clusters = [{v} for v in spec["vertices"]]
    for link in spec["links"]:
        working = sum(state[i - 1] for i in link["processors"])
        required = 1 if spec["policy"] in ("single", "dual") else 2
        if working >= required:
            ends = {link["u"], link["v"]}
            meeting = [group for group in clusters if group & ends]
            merged = set().union(*meeting)
            clusters = [group for group in clusters if not group & ends] + [merged]
    return len(clusters) == 1


def oracle_formula(spec, variables):
    """Independent resource predicates and synchronous reachability for SMT."""
    import z3

    ports = list(spec["vertices"])
    reachable = {v: z3.BoolVal(v == ports[0]) for v in ports}
    for _ in range(len(ports) - 1):
        choices = {v: [reachable[v]] for v in ports}
        for link in spec["links"]:
            indicators = [z3.If(variables[i - 1], 1, 0) for i in link["processors"]]
            required = 1 if spec["policy"] in ("single", "dual") else 2
            ready = z3.Sum(indicators) >= required
            choices[link["v"]].append(z3.And(ready, reachable[link["u"]]))
            choices[link["u"]].append(z3.And(ready, reachable[link["v"]]))
        reachable = {v: z3.Or(*terms) for v, terms in choices.items()}
    return z3.And(*reachable.values())
