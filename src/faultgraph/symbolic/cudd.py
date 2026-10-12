"""Actual dd.cudd/CUDD compilation, with portable diagram export and exact WMC."""

from dataclasses import dataclass

from ..model import ModelError, validate_state
from ..reliability import probabilities
from .circuit import Builder


@dataclass(frozen=True)
class Diagram:
    n: int
    nodes: tuple
    root: int

    def __post_init__(self):
        if (
            type(self.n) is not int
            or not 1 <= self.n <= 64
            or type(self.nodes) is not tuple
            or len(self.nodes) > 100000
        ):
            raise ModelError("invalid decision diagram envelope")
        supports = [0, 0]
        for index, item in enumerate(self.nodes, 2):
            if type(item) is not tuple or len(item) != 3:
                raise ModelError("invalid decision node")
            var, low, high = item
            if (
                type(var) is not int
                or not 0 <= var < self.n
                or any(type(c) is not int or not 0 <= c < index for c in (low, high))
            ):
                raise ModelError("decision nodes must reference earlier children")
            below = supports[low] | supports[high]
            if below & (1 << var):
                raise ModelError("a decision variable repeats along a path")
            supports.append(below | (1 << var))
        if type(self.root) is not int or not 0 <= self.root < len(self.nodes) + 2:
            raise ModelError("invalid decision root")

    def evaluate(self, state):
        state = validate_state(state, self.n)
        node = self.root
        while node > 1:
            var, low, high = self.nodes[node - 2]
            node = high if state[var] else low
        return bool(node)

    def reliability(self, ps):
        ps = probabilities(ps, self.n)
        values = [0.0, 1.0]
        for var, low, high in self.nodes:
            values.append((1 - ps[var]) * values[low] + ps[var] * values[high])
        return values[self.root]

    def circuit(self):
        b = Builder(self.n)
        values = [0, 1]
        for var, low, high in self.nodes:
            x = 2 * (var + 1)
            values.append(b.lor(b.land(x, values[high]), b.land(x ^ 1, values[low])))
        return b.finish(values[self.root])

    def to_dict(self):
        return {
            "schema": "faultgraph-decision-1",
            "n": self.n,
            "root": self.root,
            "nodes": [list(item) for item in self.nodes],
        }


class Compiled:
    def __init__(self, circuit, *, reorder=False):
        from dd import cudd

        self.manager = b = cudd.BDD()
        b.configure(reordering=reorder, max_memory=256 * 1024 * 1024)
        b.declare(*(f"x{i}" for i in range(1, circuit.n + 1)))
        values = [b.false] + [b.var(f"x{i}") for i in range(1, circuit.n + 1)]
        # Keep only still-needed gate roots, allowing CUDD garbage collection.
        uses = [0] * (circuit.n + len(circuit.gates) + 1)
        for a, c in circuit.gates:
            uses[a >> 1] += 1
            uses[c >> 1] += 1
        uses[circuit.output >> 1] += 1

        def lit(v):
            return ~values[v >> 1] if v & 1 else values[v >> 1]

        for a, c in circuit.gates:
            values.append(lit(a) & lit(c))
            for value in (a, c):
                node = value >> 1
                uses[node] -= 1
                if uses[node] == 0:
                    values[node] = None
            if len(b) > 100000:
                raise ModelError("CUDD intermediate manager-node limit")
        self.root = lit(circuit.output)
        values.clear()
        if reorder:
            b.reorder()
        self.n = circuit.n
        self.order = [b.var_at_level(i) for i in range(circuit.n)]
        self.diagram = self._export()

    def _export(self):
        b, nodes, seen = self.manager, [], {}

        def visit(node):
            if node == b.false:
                return 0
            if node == b.true:
                return 1
            key = int(node)
            if key in seen:
                return seen[key]
            level, low, high = b.succ(node)
            if node.negated:
                low, high = ~low, ~high
            a, c = visit(low), visit(high)
            nodes.append((int(b.var_at_level(level)[1:]) - 1, a, c))
            if len(nodes) > 100000:
                raise ModelError("decision export-node limit")
            seen[key] = len(nodes) + 1
            return seen[key]

        root = visit(self.root)
        return Diagram(self.n, tuple(nodes), root)

    def evaluate_native(self, state):
        state = validate_state(state, self.n)
        value = self.manager.let({f"x{i + 1}": bool(v) for i, v in enumerate(state)}, self.root)
        return value == self.manager.true
