"""Additional public-source checks; no changes to historical reproductions.

MLE recurrence from IJEM p.256 / AAIT p.368; HAIT pp.37–38; AAIT pp.375–376.
Paper attributions are retained in research/v2/PRIOR_ART_GAP_MATRIX.md.
"""

import json
from functools import lru_cache
from itertools import product
from pathlib import Path
from time import perf_counter

from ..evaluator import operational
from ..expr import TRUE, Const, Not, Or, Var
from ..expr import conj as A
from ..expr import disj as O
from ..metrics import model_metrics
from ..model import Edge, GLModel, save_model
from ..paper import write_csv
from ..subsystems import source_donor


@lru_cache(maxsize=1024)
def mle_functions(m, variables):
    """Published output-vector recurrence; balanced ceil/floor subdivision.

    Output count n-m+1. Degenerate vectors are not misrepresented as simple cycles.
    """
    n = len(variables)
    if not 1 <= m <= n:
        raise ValueError("MLE vector requires 1<=m<=n")
    if m == 1:
        return variables
    if m == n:
        return (O(*variables),)
    n1 = (n + 1) // 2
    n2 = n - n1
    left, right = variables[:n1], variables[n1:]
    funcs = list(mle_functions(m, left)) if m <= n1 else []
    for i in range(max(1, m - n1), min(n2, m - 1) + 1):
        funcs.append(O(A(*mle_functions(m - i, left)), A(*mle_functions(i, right))))
    if m <= n2:
        funcs.extend(mle_functions(m, right))
    return tuple(funcs)


def cycle(n, funcs, name):
    if len(funcs) < 3:
        raise ValueError("ordinary cycle requires at least three edges")
    vertices = tuple(f"v{i}" for i in range(len(funcs)))
    return GLModel(
        n,
        vertices,
        tuple(
            Edge(f"f{i + 1}", vertices[i], vertices[(i + 1) % len(funcs)], f)
            for i, f in enumerate(funcs)
        ),
        name,
    )


def hait9_models():
    x = tuple(Var(i) for i in range(1, 10))
    a, b, c, d, e, f, g, h, i = x
    nc1 = A(O(Not(a), Not(b), e), O(Not(e), A(d, g)))
    nc2 = O(Not(d), Not(e), Not(g))
    first = [O(v, nc1) for v in mle_functions(3, x)]
    second = [O(v, nc2) for v in mle_functions(4, x)]
    second[0] = second[1] = second[5] = TRUE
    second[2] = O(A(*mle_functions(3, x[:5])), A(f, h, i), nc2)
    second[4] = O(A(a, b, c), A(*mle_functions(3, x[5:])), nc2)
    third = [
        O(a, b, e),
        O(A(a, b), c, e),
        O(A(a, b), e),
        O(d, e, A(a, b)),
        O(A(a, b), e, A(f, g, h, i)),
        O(f, g, e, A(a, b)),
        O(A(f, g), A(h, i), e, A(a, b)),
        O(h, i, e, A(a, b)),
    ]
    funcs = (first, second, third)
    models = {}
    for prime in (False, True):
        maps = []
        for block, fs in enumerate(funcs):
            mp = {j: f"{block}:{j}" for j in range(len(fs))}
            if prime and block == 1:
                for j in (0, 1, 2, 5):
                    mp[j] = "1:merged"
            maps.append(mp)
        joins = (
            [((0, 1), (1, 4)), ((1, 3), (2, 7))] if prime else [((0, 2), (1, 5)), ((1, 2), (2, 6))]
        )
        for k, (left, right) in enumerate(joins):
            maps[left[0]][left[1]] = maps[right[0]][right[1]] = f"join{k}"
        vertices = tuple(dict.fromkeys(v for mp in maps for v in mp.values()))
        edges = []
        for block, fs in enumerate(funcs):
            for j, predicate in enumerate(fs):
                u, v = maps[block][j], maps[block][(j + 1) % len(fs)]
                if u != v:
                    edges.append(Edge(f"{block}:f{j + 1}", u, v, predicate))
        name = "HAIT9-M-prime" if prime else "HAIT9-M"
        models[name] = GLModel(
            9,
            vertices,
            tuple(edges),
            name,
            {"source": "10.15276/hait.09.2026.03", "pages": "37–38", "human_review": "PENDING"},
        )
    return models


def hait9_oracle(state):
    tolerance = (
        4 if state[3] and state[4] and state[6] else 3 if (state[0] and state[1]) or state[4] else 2
    )
    return 9 - sum(state) <= tolerance


def z3_expr(expr, variables, cache=None):
    import z3

    cache = {} if cache is None else cache
    if expr in cache:
        return cache[expr]
    if isinstance(expr, Var):
        value = variables[expr.index - 1]
    elif isinstance(expr, Const):
        value = z3.BoolVal(expr.value)
    elif isinstance(expr, Not):
        value = z3.Not(z3_expr(expr.arg, variables, cache))
    elif isinstance(expr, Or):
        value = z3.Or(*(z3_expr(a, variables, cache) for a in expr.args))
    else:
        value = z3.And(*(z3_expr(a, variables, cache) for a in expr.args))
    cache[expr] = value
    return value


def z3_connected(model, variables):
    import z3

    size = len(model.vertices)
    ids = {v: i for i, v in enumerate(model.vertices)}
    matrix = [[z3.BoolVal(i == j) for j in range(size)] for i in range(size)]
    cache = {}
    for e in model.edges:
        u, v = ids[e.u], ids[e.v]
        value = z3_expr(e.predicate, variables, cache)
        matrix[u][v] = matrix[v][u] = value
    for k in range(size):
        for i in range(size):
            for j in range(size):
                matrix[i][j] = z3.simplify(z3.Or(matrix[i][j], z3.And(matrix[i][k], matrix[k][j])))
    return z3.And(*matrix[0])


def aait27_proof(out, timeout_ms=60000):
    import z3

    out = Path(out)
    p = z3.Bools(" ".join(f"p{i}" for i in range(1, 28)))
    inputs = []
    offset = 0
    for n, m in ((8, 3), (7, 2), (7, 3)):
        variables = tuple(Var(i) for i in range(1, n + 1))
        inputs.extend(z3_expr(f, p[offset : offset + n]) for f in mle_functions(m + 1, variables))
        offset += n
    donor, g, h, _ = source_donor(5)
    kappa = z3_connected(donor, p[22:])
    available = [
        z3.Or(
            z3_expr(g[j], p[22:]) if j < len(g) else z3.BoolVal(False),
            z3.And(z3.Not(kappa), z3_expr(f, p[22:])),
        )
        for j, f in enumerate(h)
    ]
    inputs.extend(available)
    final = cycle(
        17, mle_functions(3, tuple(Var(i) for i in range(1, 18))), "AAIT27-final-virtual-K3-17"
    )
    actual = z3_connected(final, inputs)

    def count(bits):
        return z3.Sum(*(z3.If(b, 1, 0) for b in bits))

    deficits = []
    offset = 0
    for n, m in ((8, 3), (7, 2), (7, 3)):
        missing = n - m - count(p[offset : offset + n])
        deficits.append(z3.If(missing > 0, missing, 0))
        offset += n
    donor_count = count(p[22:])
    resource = z3.If(donor_count >= 3, donor_count - 3, donor_count)
    expected = z3.Sum(*deficits) <= resource
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    solver.add(z3.Xor(actual, expected))
    (out / "aait27-equivalence.smt2").write_text(solver.to_smt2())
    start = perf_counter()
    status = solver.check()
    elapsed = perf_counter() - start
    result = {
        "solver": z3.get_version_string(),
        "timeout_ms": timeout_ms,
        "seconds": elapsed,
        "status": "UNSAT_FINITE_EQUIVALENCE"
        if status == z3.unsat
        else "COUNTEREXAMPLE"
        if status == z3.sat
        else "UNKNOWN",
        "scope": "all 2^27 physical Boolean states of the literal hierarchical Example 3 construction only",
        "human_review": "BLOCKED_NOT_PERFORMED",
        "assumptions": "all-terminal static cycles; specified donor policy; no edge independence",
    }
    if status == z3.sat:
        result["witness"] = "".join(
            "1" if z3.is_true(solver.model().eval(b, model_completion=True)) else "0" for b in p
        )
    if status == z3.unknown:
        result["reason_unknown"] = solver.reason_unknown()
    save_model(final, out / "aait27-virtual-final.json")
    (out / "aait27-result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def run(out):
    out = Path(out)
    if out.exists():
        raise ValueError("source-audit output immutable; choose a new version")
    out.mkdir(parents=True)
    rows = []
    metrics = []
    for name, model in hait9_models().items():
        save_model(model, out / (name + ".json"))
        for state in product((0, 1), repeat=9):
            a = operational(model, state)
            b = hait9_oracle(state)
            rows.append(
                {
                    "model": name,
                    "state": "".join(map(str, state)),
                    "actual": int(a),
                    "oracle": int(b),
                    "match": int(a == b),
                }
            )
        metric = model_metrics(model)
        metrics.append(
            {
                "model": name,
                **metric,
                "published_total": 202,
                "published_and": 76,
                "published_or": 96,
                "published_not": 30,
            }
        )
    write_csv(out / "hait9-states.csv", rows)
    write_csv(out / "hait9-metrics.csv", metrics)
    # Independent recurrence resource-count audit before use in the large source.
    checked = 0
    for n in range(1, 9):
        for m in range(1, n + 1):
            fs = mle_functions(m, tuple(Var(i) for i in range(1, n + 1)))
            for state in product((0, 1), repeat=n):
                checked += 1
                if sum(f.evaluate(state) for f in fs) != min(n - m + 1, sum(state)):
                    raise ValueError(f"MLE recurrence witness n={n},m={m},state={state}")
    result = {
        "hait9_comparisons": len(rows),
        "hait9_mismatches": sum(not r["match"] for r in rows),
        "hait9_metric_matches": all(
            m["total"] == 202 and m["and"] == 76 and m["or"] == 96 and m["not"] == 30
            for m in metrics
        ),
        "mle_vector_checked_instances": checked,
        "aait27": aait27_proof(out),
    }
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
