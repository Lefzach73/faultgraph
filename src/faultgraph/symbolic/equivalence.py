"""General finite symbolic equivalence; UNSAT applies only to the encoded pair."""

from pathlib import Path
from time import perf_counter

from ..evaluator import operational
from ..expr import Const, Not, Or, Var
from ..model import GLModel, ModelError
from .circuit import Circuit


def graph_formula(model, variables):
    """Boolean Floyd-Warshall, independent of the rooted-reachability compiler."""
    import z3

    if len(model.vertices) > 128:
        raise ModelError("SMT graph scope is V<=128")
    cache = {}

    def expr(e):
        if e in cache:
            return cache[e]
        if isinstance(e, Const):
            value = z3.BoolVal(e.value)
        elif isinstance(e, Var):
            value = variables[e.index - 1]
        elif isinstance(e, Not):
            value = z3.Not(expr(e.arg))
        else:
            value = (z3.Or if isinstance(e, Or) else z3.And)(*[expr(a) for a in e.args])
        cache[e] = value
        return value

    size = len(model.vertices)
    ids = {v: i for i, v in enumerate(model.vertices)}
    matrix = [[z3.BoolVal(i == j) for j in range(size)] for i in range(size)]
    for edge in model.edges:
        i, j = ids[edge.u], ids[edge.v]
        matrix[i][j] = matrix[j][i] = expr(edge.predicate)
    for k in range(size):
        # Copying is unnecessary: Boolean reachability makes this standard
        # in-place Floyd-Warshall update valid with true diagonal entries.
        for i in range(size):
            for j in range(i + 1, size):
                value = z3.Or(matrix[i][j], z3.And(matrix[i][k], matrix[k][j]))
                matrix[i][j] = matrix[j][i] = value
    return z3.And(*matrix[0])


def circuit_formula(circuit, variables):
    import z3

    values = [z3.BoolVal(False), *variables]

    def lit(value):
        node = values[value >> 1]
        return z3.Not(node) if value & 1 else node

    for a, b in circuit.gates:
        values.append(z3.And(lit(a), lit(b)))
    return lit(circuit.output)


def check(left, right, *, timeout_ms=30000, smt_path=None):
    import z3

    if type(timeout_ms) is not int or timeout_ms < 1:
        raise ModelError("SMT timeout must be a positive integer")
    if not isinstance(left, (GLModel, Circuit)) or not isinstance(right, (GLModel, Circuit)):
        raise ModelError("expected GLModel or safe Circuit")
    n = left.num_processors if isinstance(left, GLModel) else left.n
    other_n = right.num_processors if isinstance(right, GLModel) else right.n
    if n != other_n:
        raise ModelError("processor domains differ")
    start = perf_counter()
    variables = [z3.Bool(f"x{i}") for i in range(1, n + 1)]

    def encode(value):
        return (
            graph_formula(value, variables)
            if isinstance(value, GLModel)
            else circuit_formula(value, variables)
        )

    a, b = encode(left), encode(right)
    solver = z3.Solver()
    solver.set(timeout=timeout_ms, random_seed=0)
    solver.add(z3.Xor(a, b))
    if smt_path is not None:
        Path(smt_path).write_text(solver.to_smt2())
    encoded = perf_counter()
    result = solver.check()
    record = {
        "status": "UNSAT_FINITE_EQUIVALENCE"
        if result == z3.unsat
        else "COUNTEREXAMPLE"
        if result == z3.sat
        else "UNKNOWN",
        "num_processors": n,
        "left_hash": left.digest,
        "right_hash": right.digest,
        "solver": z3.get_version_string(),
        "timeout_ms": timeout_ms,
        "encoding_seconds": encoded - start,
        "solver_seconds": perf_counter() - encoded,
        "witness": None,
        "scope": "all Boolean assignments for this encoded pair; not a universal implementation proof",
    }
    if result == z3.unknown:
        record["reason"] = solver.reason_unknown()
    elif result == z3.sat:
        witness = tuple(
            int(z3.is_true(solver.model().eval(v, model_completion=True))) for v in variables
        )

        def evaluate(value):
            return (
                operational(value, witness)
                if isinstance(value, GLModel)
                else value.evaluate(witness)
            )

        record.update(
            witness="".join(map(str, witness)), left=evaluate(left), right=evaluate(right)
        )
        if record["left"] == record["right"]:
            record["status"] = "ENCODING_ERROR"
    return record
