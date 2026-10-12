"""Classical block factorization and bounded rooted-reachability circuits."""

from ..model import ModelError
from .circuit import Builder


def edge_blocks(model):
    """Tarjan edge-stack decomposition; returns None for disconnected topology."""
    if len(model.vertices) > 128:
        raise ModelError("symbolic graph scope is V<=128")
    adj = {v: [] for v in model.vertices}
    for i, e in enumerate(model.edges):
        adj[e.u].append((e.v, i))
        adj[e.v].append((e.u, i))
    times, low, stack, blocks = {}, {}, [], []

    def dfs(u, parent_edge=-1):
        times[u] = low[u] = len(times)
        for v, eid in sorted(adj[u]):
            if eid == parent_edge:
                continue
            if v not in times:
                stack.append(eid)
                dfs(v, eid)
                low[u] = min(low[u], low[v])
                if low[v] >= times[u]:
                    block = []
                    while True:
                        top = stack.pop()
                        block.append(top)
                        if top == eid:
                            break
                    blocks.append(tuple(sorted(block)))
            elif times[v] < times[u]:
                stack.append(eid)
                low[u] = min(low[u], times[v])

    dfs(model.vertices[0])
    return sorted(blocks) if len(times) == len(model.vertices) else None


def connectivity_circuit(model, *, factor=False):
    if len(model.vertices) > 128:
        raise ModelError("symbolic graph scope is V<=128")
    b = Builder(model.num_processors)
    blocks = edge_blocks(model)
    if blocks is None:
        return b.finish(0)
    if len(model.vertices) == 1:
        return b.finish(1)
    literals = [b.expression(e.predicate) for e in model.edges]
    groups = blocks if factor else [tuple(range(len(model.edges)))]
    outputs = []
    for group in groups:
        vertices = sorted({v for i in group for v in (model.edges[i].u, model.edges[i].v)})
        reach = {v: int(v == vertices[0]) for v in vertices}
        # Synchronous rounds: all paths of at most |V|-1 edges suffice.
        for _ in range(len(vertices) - 1):
            new = dict(reach)
            for i in group:
                e, lit = model.edges[i], literals[i]
                new[e.u] = b.lor(new[e.u], b.land(reach[e.v], lit))
                new[e.v] = b.lor(new[e.v], b.land(reach[e.u], lit))
            if new == reach:
                break
            reach = new
        outputs.append(b.all(reach.values()))
    return b.finish(b.all(outputs))
