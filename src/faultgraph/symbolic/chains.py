"""Direct CUDD connectivity and obligation-preserving degree-two chains.

Series reduction is established prior art. The global orphan obligation makes
the Boolean reduction safe for correlated predicates and required inner vertices.
"""

from ..expr import Const, Not, Or, Var
from ..model import ModelError, validate_state
from .cudd import Diagram


def topology_plan(model, *, extract_chains=True):
    if len(model.vertices) > 128:
        raise ModelError("symbolic graph scope is V<=128")
    adjacency = {v: [] for v in model.vertices}
    for index, edge in enumerate(model.edges):
        adjacency[edge.u].append((edge.v, index))
        adjacency[edge.v].append((edge.u, index))
    root = min(model.vertices, key=lambda v: (-len(adjacency[v]), v))
    reached, stack = {root}, [root]
    while stack:
        for neighbor, _ in adjacency[stack.pop()]:
            if neighbor not in reached:
                reached.add(neighbor)
                stack.append(neighbor)
    if len(reached) != len(model.vertices):
        return root, None, None
    if not extract_chains:
        return root, list(model.vertices), []
    boundaries = {v for v in model.vertices if len(adjacency[v]) != 2} | {root}
    visited, paths = set(), []
    for start in sorted(boundaries):
        for neighbor, first in sorted(adjacency[start]):
            if first in visited:
                continue
            vertices, edges = [start, neighbor], [first]
            visited.add(first)
            current, previous_edge = neighbor, first
            while current not in boundaries:
                next_vertex, eid = next(p for p in adjacency[current] if p[1] != previous_edge)
                if eid in visited:
                    raise ModelError("chain decomposition revisited an edge")
                edges.append(eid)
                visited.add(eid)
                vertices.append(next_vertex)
                current, previous_edge = next_vertex, eid
            paths.append(
                {
                    "start": start,
                    "end": current,
                    "internal_vertices": vertices[1:-1],
                    "edge_indices": edges,
                }
            )
    if len(visited) != len(model.edges):
        raise ModelError("chain decomposition did not cover every edge")
    return root, sorted(boundaries), paths


class NativeCompiled:
    """Same direct symbolic engine with/without chain summaries; no truth labels."""

    def __init__(self, model, *, compress=False, unsafe_drop_obligation=False, reorder=True):
        from dd import cudd

        root_vertex, boundaries, paths = topology_plan(model, extract_chains=compress)
        self.manager = b = cudd.BDD()
        b.configure(reordering=reorder, max_memory=256 * 1024 * 1024)
        b.declare(*(f"x{i}" for i in range(1, model.num_processors + 1)))
        self.n = model.num_processors
        self.apply_calls = 0
        self.peak_manager_nodes = len(b)
        self.lineage = []
        self.reduced_vertices = len(model.vertices)
        self.reduced_edges = len(model.edges)

        def op(kind, a, c):
            self.apply_calls += 1
            value = a & c if kind == "and" else a | c
            count = len(b)
            self.peak_manager_nodes = max(self.peak_manager_nodes, count)
            if count > 100000:
                raise ModelError("CUDD intermediate manager-node limit")
            return value

        cache = {}

        def expression(expr):
            if expr in cache:
                return cache[expr]
            if isinstance(expr, Const):
                value = b.true if expr.value else b.false
            elif isinstance(expr, Var):
                value = b.var(f"x{expr.index}")
            elif isinstance(expr, Not):
                value = ~expression(expr.arg)
            else:
                is_or = isinstance(expr, Or)
                value = b.false if is_or else b.true
                for item in expr.args:
                    value = op("or" if is_or else "and", value, expression(item))
            cache[expr] = value
            return value

        def reach(vertices, edges):
            reached = {v: b.true if v == root_vertex else b.false for v in vertices}
            for _ in range(len(vertices) - 1):
                new = dict(reached)
                for u, v, f in edges:
                    new[u] = op("or", new[u], op("and", reached[v], f))
                    new[v] = op("or", new[v], op("and", reached[u], f))
                if all(new[v] == reached[v] for v in vertices):
                    break  # canonical equality, not merely graph distance
                reached = new
            value = b.true
            for vertex in vertices:
                value = op("and", value, reached[vertex])
            return value

        def build():
            if boundaries is None:
                return b.false
            predicates = [expression(e.predicate) for e in model.edges]
            if not compress or not any(path["internal_vertices"] for path in paths):
                return reach(
                    model.vertices,
                    [(e.u, e.v, p) for e, p in zip(model.edges, predicates, strict=True)],
                )
            obligation, reduced = b.true, {}
            for path in paths:
                a, all_edges = b.true, b.true
                for eid in path["edge_indices"]:
                    f = predicates[eid]
                    a = op("or", op("and", a, f), all_edges)
                    all_edges = op("and", all_edges, f)
                if path["internal_vertices"]:
                    self.lineage.append(
                        {
                            **path,
                            "original_edge_ids": [model.edges[i].id for i in path["edge_indices"]],
                            "obligation": "at most one inactive edge",
                            "macro": "all chain edges active",
                        }
                    )
                if not unsafe_drop_obligation:
                    obligation = op("and", obligation, a)
                if path["start"] != path["end"]:
                    pair = tuple(sorted((path["start"], path["end"])))
                    reduced[pair] = op("or", reduced.get(pair, b.false), all_edges)
            self.reduced_vertices, self.reduced_edges = len(boundaries), len(reduced)
            connection = reach(boundaries, [(u, v, f) for (u, v), f in sorted(reduced.items())])
            return op("and", obligation, connection)

        self.root = build()
        cache.clear()  # only the operational root remains before final sifting
        if reorder:
            b.reorder()
        self.order = [b.var_at_level(i) for i in range(self.n)]
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
