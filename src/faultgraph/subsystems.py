"""Literal AAIT 2026 donor functions, Examples 1 and 3 (pp.372–375).

Romankevich, Morozov, Romankevich, Halytsky, Zacharioudakis, CC BY 4.0.
Resource bits are virtual counts, not physical processor identities. Only the
donor interface is reproduced here; no claim to reproduce the 27-processor system.
"""

import json
from functools import lru_cache
from pathlib import Path

from .evaluator import operational
from .expr import Var
from .expr import conj as A
from .expr import disj as O
from .model import Edge, GLModel, states, validate_state
from .paper import write_csv


@lru_cache(maxsize=2)
def source_donor(n):
    x = [Var(i) for i in range(1, n + 1)]
    if n == 5:
        a, b, c, d, e = x
        m = 2
        f = [O(a, b), O(A(a, b), c), O(A(a, b, c), A(d, e)), O(d, e)]
        g = [A(a, b, c, O(d, e)), A(O(A(a, b), A(O(a, b), c)), d, e)]
        h = [O(a, b, c), O(A(O(a, b), O(A(a, b), c)), A(d, e)), O(A(a, b, c), d, e)]
    elif n == 8:
        a, b, c, d, e, f0, g0, h0 = x
        m = 3
        first = A(O(a, b), O(A(a, b), A(c, d)), O(c, d))
        last = A(O(e, f0), O(A(e, f0), A(g0, h0)), O(g0, h0))
        f = [
            O(a, b, A(c, d)),
            O(A(a, b), c, d),
            O(first, A(e, f0, g0, h0)),
            O(A(a, b, c, d), last),
            O(e, f0, A(g0, h0)),
            O(A(e, f0), g0, h0),
        ]
        g = [
            A(a, b, c, d, O(A(e, f0), A(O(e, f0), O(g0, h0)), A(g0, h0))),
            A(O(A(a, b, O(c, d)), A(O(a, b), c, d)), O(A(e, f0, O(g0, h0)), A(O(e, f0), g0, h0))),
            A(O(A(a, b), A(O(a, b), O(c, d)), A(c, d)), e, f0, g0, h0),
        ]
        h = [
            O(a, b, c, d),
            O(A(O(a, b, A(c, d)), O(A(a, b), c, d)), A(e, f0, g0, h0)),
            O(first, last),
            O(A(a, b, c, d), A(O(e, f0, A(g0, h0)), O(A(e, f0), g0, h0))),
            O(e, f0, g0, h0),
        ]
    else:
        raise ValueError("only source donors n=5,m=2 and n=8,m=3 transcribed")
    vertices = tuple(f"d{i}" for i in range(len(f)))
    edges = tuple(
        Edge(f"f{i + 1}", vertices[i], vertices[(i + 1) % len(f)], p) for i, p in enumerate(f)
    )
    model = GLModel(n, vertices, edges, f"AAIT-donor-{n}", {"source": "10.15276/aait.09.2026.25"})
    return model, tuple(g), tuple(h), m


def donor_resources(state):
    state = validate_state(state, len(state))
    model, g, h, m = source_donor(len(state))
    kappa = operational(model, state)
    r = tuple(int(p.evaluate(state)) for p in g) + (0,) * (len(h) - len(g))
    o = tuple(int(p.evaluate(state)) for p in h)
    v = tuple(int(ri or (not kappa and oi)) for ri, oi in zip(r, o, strict=True))
    return {"kappa": kappa, "reserve": r, "orphan": o, "available": v, "m": m}


def count_oracle(state, m):
    """Independent resource arithmetic from source verbal donor definition."""
    working = sum(state)
    operational = working >= len(state) - m
    return operational, working - (len(state) - m) if operational else working


def reproduce_donors(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in (5, 8):
        for s in states(n):
            actual = donor_resources(s)
            expected, count = count_oracle(s, actual["m"])
            rows.append(
                {
                    "n": n,
                    "m": actual["m"],
                    "state": "".join(map(str, s)),
                    "donor_operational": int(actual["kappa"]),
                    "available_vector": "".join(map(str, actual["available"])),
                    "available_count": sum(actual["available"]),
                    "oracle_operational": int(expected),
                    "oracle_count": count,
                    "match": int(actual["kappa"] == expected and sum(actual["available"]) == count),
                }
            )
    write_csv(out / "donor_results.csv", rows)
    summary = {
        "scope": "AAIT donor interface only, n=5 and n=8, not full recipient/sliding models",
        "checked_states": len(rows),
        "mismatches": sum(not r["match"] for r in rows),
        "human_review": "PENDING",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


@lru_cache(maxsize=2)
def source_recipient(limited=False):
    """Literal AAIT Example 1 K(7,11) / Example 2 K(6,10), pp.373–374.

    Inputs are extended virtual state bits, not extra physical processors.
    """
    n = 10 if limited else 11
    x = [Var(i) for i in range(1, n + 1)]
    if not limited:
        a, b, c, d, e, f, v1, v2, v3, v4, v5 = x
        left2 = A(O(a, b, c, A(O(d, e), O(A(d, e), f))), O(A(O(a, b), O(A(a, b), c)), d, e, f))
        right2 = A(O(v1, v2), O(A(v1, v2), v3), O(A(v1, v2, v3), A(v4, v5)), O(v4, v5))
        left3 = A(
            O(a, b, c, A(d, e, f)),
            O(A(O(a, b), O(A(a, b), c)), A(O(d, e), O(A(d, e), f))),
            O(A(a, b, c), d, e, f),
        )
        right3 = A(
            O(v1, v2, v3), O(A(O(v1, v2), O(A(v1, v2), v3)), A(v4, v5)), O(A(v1, v2, v3), v4, v5)
        )
        left4 = A(
            O(a, b, c),
            O(A(O(a, b), O(A(a, b), c)), A(d, e, f)),
            O(A(a, b, c), A(O(d, e), O(A(d, e), f))),
            O(d, e, f),
        )
        right4 = A(O(v1, v2, v3, A(v4, v5)), O(A(O(v1, v2), O(A(v1, v2), v3)), v4, v5))
        left5 = A(O(a, b), O(A(a, b), c), O(A(a, b, c), A(d, e, f)), O(d, e), O(A(d, e), f))
        funcs = [
            O(a, b, c, d, e, f, A(v1, v2, v3, v4, v5)),
            O(left2, right2),
            O(left3, right3),
            O(left4, right4),
            O(left5, v1, v2, v3, v4, v5),
        ]
    else:
        a, b, c, d, e, f, e1, e2, e3, e4 = x
        left2 = A(O(a, b, c, A(d, e)), O(A(O(a, b), O(A(a, b), c)), d, e))
        right2 = A(O(f, e1), O(A(f, e1), e2), O(A(f, e1, e2), A(e3, e4)), O(e3, e4))
        left3 = A(O(a, b, c), O(A(O(a, b), O(A(a, b), c)), A(d, e)), O(A(a, b, c), d, e))
        right3 = A(
            O(f, e1, e2), O(A(O(f, e1), O(A(f, e1), e2)), A(e3, e4)), O(A(f, e1, e2), e3, e4)
        )
        left4 = A(O(a, b), O(A(a, b), c), O(A(a, b, c), A(d, e)), O(d, e))
        right4 = A(O(f, e1, e2, A(e3, e4)), O(A(O(f, e1), O(A(f, e1), e2)), e3, e4))
        funcs = [
            O(a, b, c, d, e, A(f, e1, e2, e3, e4)),
            O(left2, right2),
            O(left3, right3),
            O(left4, right4),
            O(A(a, b, c, d, e), f, e1, e2, e3, e4),
        ]
    vertices = tuple(f"r{i}" for i in range(5))
    return GLModel(
        n,
        vertices,
        tuple(
            Edge(f"f{i + 1}", vertices[i], vertices[(i + 1) % 5], p) for i, p in enumerate(funcs)
        ),
        "AAIT-recipient-limited" if limited else "AAIT-recipient",
    )


def limited_vector(v):
    """Literal L(4,5) outputs, AAIT p.373."""
    a, b, c, d, e = v
    return (int(a or b), int((a and b) or c), int((a and b and c) or (d and e)), int(d or e))


def reproduce_recipients(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    donors = {s: donor_resources(s) for s in states(8)}
    models = {False: source_recipient(False), True: source_recipient(True)}
    rows = []
    # Explicit finite exception to default n<=12: fixed published 6+8 example only.
    for s in states(14, limit=14):
        recipient, donor = s[:6], s[6:]
        resources = donors[donor]["available"]
        _, count = count_oracle(donor, 3)
        for limited, model in models.items():
            virtual = limited_vector(resources) if limited else resources
            actual = operational(model, recipient + virtual)
            expected = sum(recipient) + min(count, 4 if limited else count) >= 4
            rows.append(
                {
                    "example": 2 if limited else 1,
                    "physical_state": "".join(map(str, s)),
                    "extended_state": "".join(map(str, recipient + virtual)),
                    "oracle": int(expected),
                    "operational": int(actual),
                    "match": int(expected == actual),
                }
            )
    write_csv(out / "recipient_results.csv", rows)
    summary = {
        "scope": "AAIT Examples 1 and 2, 14 physical processors; 16384 states each",
        "checked_states": len(rows),
        "mismatches": sum(not r["match"] for r in rows),
        "human_review": "PENDING",
        "excluded": "27-processor Example 3 sliding system",
    }
    (out / "recipient_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary
