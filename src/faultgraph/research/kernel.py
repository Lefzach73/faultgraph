"""Shared safe expression DAG and exact finite bitset connectivity.

Bitset index is the integer represented by x1..xn. No generated executable code.
Scalar legacy BFS and independently authored domain oracles validate this backend.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256

from ..expr import Const, Not, Or, Var
from ..model import ModelError, validate_state


@dataclass(frozen=True)
class Program:
    n: int
    instructions: tuple
    vertices: tuple
    edges: tuple

    @classmethod
    def build(cls, model):
        instructions = []
        seen = {}

        def add(e):
            if e in seen:
                return seen[e]
            if isinstance(e, Const):
                op = ("const", e.value)
            elif isinstance(e, Var):
                op = ("var", e.index - 1)
            elif isinstance(e, Not):
                op = ("not", add(e.arg))
            else:
                op = ("or" if isinstance(e, Or) else "and", tuple(add(a) for a in e.args))
            index = len(instructions)
            instructions.append(op)
            seen[e] = index
            return index

        ids = {v: i for i, v in enumerate(model.vertices)}
        edges = tuple((ids[e.u], ids[e.v], add(e.predicate)) for e in model.edges)
        return cls(model.num_processors, tuple(instructions), model.vertices, edges)

    @property
    def dag_ops(self):
        return sum(
            1 if op == "not" else len(arg) - 1 if op in ("and", "or") else 0
            for op, arg in self.instructions
        )

    def evaluate(self, state):
        state = validate_state(state, self.n)
        values = []
        for op, arg in self.instructions:
            if op == "const":
                v = arg
            elif op == "var":
                v = bool(state[arg])
            elif op == "not":
                v = not values[arg]
            elif op == "and":
                v = all(values[i] for i in arg)
            else:
                v = any(values[i] for i in arg)
            values.append(v)
        parent = list(range(len(self.vertices)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for u, v, p in self.edges:
            if values[p]:
                parent[find(u)] = find(v)
        return len({find(i) for i in parent}) == 1


@lru_cache(maxsize=128)
def variable_masks(n):
    if type(n) is not int or not 1 <= n <= 12:
        raise ModelError("bitset exact scope requires 1 <= n <= 12")
    return tuple(sum(1 << s for s in range(1 << n) if s & (1 << (n - i - 1))) for i in range(n))


def expression_mask(expr, n, cache=None):
    if type(n) is not int or not 1 <= n <= 12:
        raise ModelError("bitset exact scope requires 1 <= n <= 12")
    cache = {} if cache is None else cache
    if expr in cache:
        return cache[expr]
    full = (1 << (1 << n)) - 1
    if isinstance(expr, Const):
        v = full if expr.value else 0
    elif isinstance(expr, Var):
        v = variable_masks(n)[expr.index - 1]
    elif isinstance(expr, Not):
        v = full ^ expression_mask(expr.arg, n, cache)
    elif isinstance(expr, Or):
        v = 0
        for a in expr.args:
            v |= expression_mask(a, n, cache)
    else:
        v = full
        for a in expr.args:
            v &= expression_mask(a, n, cache)
    cache[expr] = v
    return v


def truth_mask(model):
    variable_masks(model.num_processors)
    full = (1 << (1 << model.num_processors)) - 1
    size = len(model.vertices)
    ids = {v: i for i, v in enumerate(model.vertices)}
    matrix = [[full if i == j else 0 for j in range(size)] for i in range(size)]
    cache = {}
    for e in model.edges:
        u, v = ids[e.u], ids[e.v]
        mask = expression_mask(e.predicate, model.num_processors, cache)
        matrix[u][v] |= mask
        matrix[v][u] |= mask
    for k in range(size):
        for i in range(size):
            for j in range(size):
                matrix[i][j] |= matrix[i][k] & matrix[k][j]
    result = full
    for j in range(size):
        result &= matrix[0][j]
    return result


def finite_certificate(before, after):
    if before.num_processors != after.num_processors:
        raise ModelError("processor domain changed")
    if before.num_processors > 12:
        return {"status": "NOT_CHECKED", "checked_states": 0}
    difference = truth_mask(before) ^ truth_mask(after)
    witness = (
        format((difference & -difference).bit_length() - 1, f"0{before.num_processors}b")
        if difference
        else None
    )
    return {
        "status": "COUNTEREXAMPLE" if difference else "EXHAUSTIVE_PASS",
        "checked_states": 1 << before.num_processors,
        "witness": witness,
        "backend": "bitset Boolean Warshall; finite scope only",
        "before_hash": before.digest,
        "after_hash": after.digest,
    }


def structural_key(model):
    data = model.to_dict()
    data.pop("model_id")
    data.pop("metadata")
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
