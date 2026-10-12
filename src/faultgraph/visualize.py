"""DOT export with escaped IDs and every vertex, including isolated vertices."""

import json

from .evaluator import active_edges


def to_dot(model, state=None):
    active = (
        {e.id for e in active_edges(model, state)}
        if state is not None
        else {e.id for e in model.edges}
    )
    lines = ["graph faultgraph {"]
    lines.extend(f"  {json.dumps(v)};" for v in model.vertices)
    lines.extend(
        f"  {json.dumps(e.u)} -- {json.dumps(e.v)} [label={json.dumps(e.id)}, style={'solid' if e.id in active else 'dashed'}];"
        for e in model.edges
    )
    return "\n".join(lines + ["}", ""])
