"""Safe, bounded AIG interchange: constants, inputs, ANDs, complemented edges.

No model-provided code is executed. AIG nodes are not GL graph vertices.
"""

import json
from dataclasses import dataclass
from hashlib import sha256

from ..expr import Const, Not, Or, Var
from ..model import ModelError, validate_state


@dataclass(frozen=True)
class Circuit:
    n: int
    gates: tuple[tuple[int, int], ...]
    output: int

    def __post_init__(self):
        if type(self.n) is not int or not 1 <= self.n <= 64:
            raise ModelError("symbolic processor domain is 1..64")
        if type(self.gates) is not tuple or len(self.gates) > 100000:
            raise ModelError("circuit requires a tuple of at most100000 AND gates")
        for index, pair in enumerate(self.gates, self.n + 1):
            if (
                type(pair) is not tuple
                or len(pair) != 2
                or any(type(v) is not int or not 0 <= v < 2 * index for v in pair)
            ):
                raise ModelError("gate literals must refer only to constants/earlier nodes")
        if type(self.output) is not int or not 0 <= self.output < 2 * (
            self.n + len(self.gates) + 1
        ):
            raise ModelError("invalid circuit output literal")

    def evaluate(self, state):
        values = [False, *validate_state(state, self.n)]
        for a, b in self.gates:
            values.append((values[a >> 1] ^ (a & 1)) & (values[b >> 1] ^ (b & 1)))
        return bool(values[self.output >> 1] ^ (self.output & 1))

    def to_dict(self):
        return {
            "schema": "faultgraph-aig-1",
            "n": self.n,
            "gates": [list(g) for g in self.gates],
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, data):
        if (
            type(data) is not dict
            or set(data) != {"schema", "n", "gates", "output"}
            or data["schema"] != "faultgraph-aig-1"
        ):
            raise ModelError("invalid AIG schema")
        if type(data["gates"]) is not list or any(type(g) is not list for g in data["gates"]):
            raise ModelError("AIG gates must be arrays")
        return cls(data["n"], tuple(tuple(g) for g in data["gates"]), data["output"])

    @property
    def digest(self):
        return sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()

    def aag(self):
        total = self.n + len(self.gates)
        lines = [f"aag {total} {self.n} 0 1 {len(self.gates)}"]
        lines += [str(2 * i) for i in range(1, self.n + 1)] + [str(self.output)]
        lines += [f"{2 * i} {a} {b}" for i, (a, b) in enumerate(self.gates, self.n + 1)]
        lines += [f"i{i} x{i + 1}" for i in range(self.n)] + [
            "o0 operational",
            "c",
            "FaultGraph safe AIG",
        ]
        return "\n".join(lines) + "\n"

    def blif(self):
        lines = [
            ".model faultgraph",
            ".inputs " + " ".join(f"x{i}" for i in range(1, self.n + 1)),
            ".outputs operational",
            ".names z0",
        ]

        def name(lit):
            i = lit >> 1
            return "z0" if not i else f"x{i}" if i <= self.n else f"g{i}"

        for i, (a, b) in enumerate(self.gates, self.n + 1):
            lines += [f".names {name(a)} {name(b)} g{i}", f"{1 - (a & 1)}{1 - (b & 1)} 1"]
        lines += [f".names {name(self.output)} operational", f"{1 - (self.output & 1)} 1", ".end"]
        return "\n".join(lines) + "\n"


class Builder:
    def __init__(self, n, max_gates=100000):
        if type(n) is not int or not 1 <= n <= 64:
            raise ModelError("symbolic processor domain is 1..64")
        self.n, self.max_gates = n, max_gates
        self.gates, self.unique, self.expressions = [], {}, {}

    def land(self, a, b):
        if a == 0 or b == 0 or a == (b ^ 1):
            return 0
        if a == 1:
            return b
        if b == 1 or a == b:
            return a
        pair = tuple(sorted((a, b)))
        if pair not in self.unique:
            if len(self.gates) >= self.max_gates:
                raise ModelError("AIG construction gate limit")
            self.gates.append(pair)
            self.unique[pair] = 2 * (self.n + len(self.gates))
        return self.unique[pair]

    def lor(self, a, b):
        return self.land(a ^ 1, b ^ 1) ^ 1

    def all(self, values):
        result = 1
        for value in values:
            result = self.land(result, value)
        return result

    def expression(self, expr):
        if expr in self.expressions:
            return self.expressions[expr]
        if isinstance(expr, Const):
            out = int(expr.value)
        elif isinstance(expr, Var):
            if expr.index > self.n:
                raise ModelError("expression variable outside circuit domain")
            out = 2 * expr.index
        elif isinstance(expr, Not):
            out = self.expression(expr.arg) ^ 1
        elif isinstance(expr, Or):
            out = 0
            for item in expr.args:
                out = self.lor(out, self.expression(item))
        else:
            out = self.all(self.expression(item) for item in expr.args)
        self.expressions[expr] = out
        return out

    def finish(self, output):
        # Remove dangling gates without changing the declared processor domain.
        needed = set()
        stack = [output >> 1]
        while stack:
            node = stack.pop()
            if node <= self.n or node in needed:
                continue
            needed.add(node)
            stack.extend(lit >> 1 for lit in self.gates[node - self.n - 1])
        mapping = {i: i for i in range(self.n + 1)}
        gates = []
        for old in sorted(needed):
            gates.append(tuple(2 * mapping[v >> 1] + (v & 1) for v in self.gates[old - self.n - 1]))
            mapping[old] = self.n + len(gates)
        return Circuit(self.n, tuple(gates), 2 * mapping[output >> 1] + (output & 1))


def parse_aag(text, expected_n):
    lines = text.splitlines()
    header = lines[0].split() if lines else []
    if len(header) != 6 or header[0] != "aag":
        raise ModelError("only combinational ASCII AIGER is supported")
    m, n, latches, outputs, count = map(int, header[1:])
    if n != expected_n or latches or outputs != 1 or m != n + count or count > 100000:
        raise ModelError("unsupported AIGER dimensions/domain")
    if [int(v) for v in lines[1 : n + 1]] != list(range(2, 2 * n + 1, 2)):
        raise ModelError("AIGER input IDs changed")
    output = int(lines[n + 1])
    gates = []
    for index, line in enumerate(lines[n + 2 : n + 2 + count], n + 1):
        lhs, a, b = map(int, line.split())
        if lhs != 2 * index:
            raise ModelError("AIGER gates must be topologically numbered")
        gates.append((a, b))
    if len(gates) != count:
        raise ModelError("truncated AIGER")
    return Circuit(n, tuple(gates), output)
