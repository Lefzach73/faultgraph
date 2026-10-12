"""Reference BFS with all vertices retained, including isolated ones."""

from .model import validate_state


def active_edges(model, state):
    s = validate_state(state, model.num_processors)
    return tuple(e for e in model.edges if e.predicate.evaluate(s))


def connected(vertices, edges):
    adjacency = {v: set() for v in vertices}
    for e in edges:
        adjacency[e.u].add(e.v)
        adjacency[e.v].add(e.u)
    reached, stack = {vertices[0]}, [vertices[0]]
    while stack:
        v = stack.pop()
        for neighbor in adjacency[v] - reached:
            reached.add(neighbor)
            stack.append(neighbor)
    return len(reached) == len(vertices)


def operational(model, state):
    return connected(model.vertices, active_edges(model, state))


def conditioned_operational(model, state):
    s = validate_state(state, model.models[0].num_processors)
    selected = [m for c, m in zip(model.selectors, model.models, strict=False) if c.evaluate(s)]
    return operational(selected[0], s)
