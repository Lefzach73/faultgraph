"""Versioned tree-operation counts; DAG sharing is reported separately."""

import json

from .expr import complexity


def model_metrics(model):
    counts = [complexity(e.predicate) for e in model.edges]
    totals = {k: sum(c[k] for c in counts) for k in ("and", "or", "not", "total", "tree_nodes")}
    # Cross-edge DAG sharing: equal immutable AST subtrees are counted once.
    nodes, stack = set(), [e.predicate for e in model.edges]
    while stack:
        e = stack.pop()
        if e in nodes:
            continue
        nodes.add(e)
        if hasattr(e, "args"):
            stack.extend(e.args)
        elif hasattr(e, "arg"):
            stack.append(e.arg)
    return {
        "vertices": len(model.vertices),
        "edges": len(model.edges),
        **totals,
        "dag_nodes": len(nodes),
        "serialized_bytes": len(json.dumps(model.to_dict(), sort_keys=True).encode()),
        "count_method": "tree-binary-v1; n-ary AND/OR count arity-1, each NOT occurrence counts 1",
    }
