"""Small finite ROBDD baseline, fixed x1..xn order; synthesis budget n<=12.

This implementation is a reference backend, not PyEDA, SMT, or a scalable proof
engine. No exponential construction cost is hidden from benchmark timings.
"""

from dataclasses import dataclass

from .model import states, validate_state
from .reliability import probabilities


@dataclass(frozen=True)
class BDD:
    n: int
    root: int
    nodes: tuple[tuple[int, int, int] | None, ...]

    @classmethod
    def from_indicator(cls, n, indicator):
        values = tuple(int(bool(indicator(s))) for s in states(n))
        nodes, unique = [None, None], {}

        def build(level, values):
            if all(v == values[0] for v in values):
                return values[0]
            middle = len(values) // 2
            low, high = build(level + 1, values[:middle]), build(level + 1, values[middle:])
            if low == high:
                return low
            key = (level, low, high)
            if key not in unique:
                unique[key] = len(nodes)
                nodes.append(key)
            return unique[key]

        root = build(0, values)
        return cls(n, root, tuple(nodes))

    def evaluate(self, state):
        state = validate_state(state, self.n)
        node = self.root
        while node > 1:
            index, low, high = self.nodes[node]
            node = high if state[index] else low
        return bool(node)

    def reliability(self, ps):
        ps = probabilities(ps, self.n)
        cache = {0: 0.0, 1: 1.0}

        def visit(node):
            if node not in cache:
                i, low, high = self.nodes[node]
                cache[node] = (1 - ps[i]) * visit(low) + ps[i] * visit(high)
            return cache[node]

        return visit(self.root)
