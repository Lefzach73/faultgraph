"""Literal public-source transcription, IJEM pp.259–264, Figs 3–5, Table 1.

Original mathematics: Vitaliy Romankevich, Kostiantyn Morozov, Alexei
Romankevich, Petro Malezhyk, Lefteris Zacharioudakis (2026), CC BY 4.0.
This computational transcription still requires independent human review.
"""

import csv
import json
from hashlib import sha256
from pathlib import Path

from .equivalence import check_functions, check_models
from .evaluator import operational
from .expr import TRUE, Not, Var
from .expr import conj as A
from .expr import disj as O
from .metrics import model_metrics
from .model import ConditionedModel, Edge, GLModel, ModelError, load_model, save_model, states
from .oracle import exceptional
from .transform import combine_aligned, combine_wedge, split_vertex, zero_edge

ACCEPTED = (
    "00111011",
    "00111101",
    "01010111",
    "01011101",
    "01011110",
    "01100111",
    "01101110",
    "01111010",
    "01111100",
    "10011011",
    "10011101",
    "10101011",
    "10110110",
    "10111010",
    "10111100",
    "11000111",
    "11001011",
    "11001101",
    "11001110",
    "11011001",
    "11011100",
    "11100110",
)
B1 = (
    "01010111",
    "01011110",
    "01100111",
    "01101110",
    "10110110",
    "11000111",
    "11001110",
    "11100110",
)
B2 = tuple(s for s in ACCEPTED if s not in B1)
PUBLISHED = {
    "K12": {"vertices": 8, "edges": 12, "or": 21, "and": 35, "not": 9, "total": 65},
    "K12-prime": {"vertices": 8, "edges": 11, "or": 23, "and": 37, "not": 13, "total": 73},
    "M": {"vertices": 14, "edges": 19, "or": 33, "and": 29, "not": 14, "total": 76},
    "M-prime": {"vertices": 12, "edges": 16, "or": 32, "and": 29, "not": 12, "total": 73},
}
V = tuple("abgde zht".replace(" ", ""))
X = Var


def oracle(state):
    return exceptional(state, 2, ACCEPTED)


def build(name, vertices, incidences, funcs):
    return GLModel(
        8,
        tuple(vertices),
        tuple(
            Edge(f"f{i + 1}", u, v, f)
            for i, ((u, v), f) in enumerate(zip(incidences, funcs, strict=True))
        ),
        name,
        {
            "source": "10.5815/ijem.2026.03.15",
            "license": "CC-BY-4.0",
            "transcription": "AI-assisted, human reviewer pending",
        },
    )


def source_models():
    x1, x2, x3, x4, x5, x6, x7, x8 = map(X, range(1, 9))
    n6, n7 = Not(x6), Not(x7)
    c = A(x6, x7)
    nc = O(n6, n7)
    k1funcs = [
        O(x1, x2),
        O(A(x1, x2), A(x3, x4)),
        O(x3, x4),
        O(A(x1, x2, x3, x4), A(x5, x6, x7, x8)),
        O(x5, x6),
        O(A(x5, x6), A(x7, x8)),
        O(x7, x8),
        A(x1, x3, x6, x7),
        A(x2, x6, x7),
    ]
    k2funcs = [O(X(i + 1), A(*(X((i + j) % 8 + 1) for j in range(1, 4)))) for i in range(8)]
    k2funcs += [A(x4, x5), A(x1, x5, x8)]
    k1vertices = tuple("abgdezh")
    cycle1 = list(zip(k1vertices, k1vertices[1:] + k1vertices[:1], strict=False))
    cycle2 = list(zip(V, V[1:] + V[:1], strict=False))
    k1 = build("K1-prime", k1vertices, cycle1 + [("a", "e"), ("b", "d")], k1funcs)
    k2 = build("K2-prime", V, cycle2 + [("t", "g"), ("t", "d")], k2funcs)
    f = [
        O(x1, A(x2, O(A(x3, x4), c))),
        O(A(x2, O(x1, n6, n7)), A(x3, x4, O(x5, c))),
        O(x3, A(x4, x6, O(x5, x7))),
        O(A(x4, O(A(x1, x2, x3), n6, n7)), A(x5, x6, x7, x8)),
        O(x5, c),
        O(A(x1, x7, x8), A(x6, O(x5, n7, x8))),
        O(x7, A(x8, O(A(x1, x2), c))),
        O(A(x1, x2, x3), c, x8),
        A(x4, x5, nc),
        A(x2, x6, x7),
        A(x1, x5, x8, nc),
        A(x1, x3, x6, x7),
    ]
    fp = [
        O(A(x1, O(x2, n6, n7)), A(x3, x4, O(x2, c))),
        O(A(x2, nc), A(x3, x4, x5), A(x6, x7, O(x3, x4))),
        O(A(x3, O(A(x1, x2, x4), n6, n7)), A(x5, x6, O(A(x4, n7), A(x7, x8)))),
        O(x4, c),
        O(x5, A(x6, x7, x8)),
        O(A(x1, x7, x8), x6),
        O(A(x1, x2, x8), x7),
        O(A(x1, x2, x3), A(x6, x7, O(x1, x2)), A(x8, nc)),
        A(x2, x6, x7),
        A(x4, x5, nc),
        A(x1, O(A(x3, x6, x7), A(x5, x8, nc))),
    ]
    k12 = build("K12", V, cycle2 + [("t", "g"), ("b", "d"), ("t", "d"), ("a", "e")], f)
    kp = build("K12-prime", V, cycle2 + [("a", "g"), ("t", "g"), ("t", "d")], fp)
    # Independently reconstruct Eq (2) from Fig 4, without using simplified f.
    a = split_vertex(k1, "a", "t", ["f7"], "f10")
    a0 = zero_edge(a.model, "t", "g", "f11")
    a1 = zero_edge(a0.model, "t", "d", "f12")
    amap = {
        "f1": "f1",
        "f2": "f2",
        "f3": "f3",
        "f4": "f4",
        "f5": "f5",
        "f6": "f6",
        "f7": "f7",
        "f10": "f8",
        "f11": "f9",
        "f9": "f10",
        "f12": "f11",
        "f8": "f12",
    }
    aa = GLModel(
        8,
        V,
        tuple(Edge(amap[e.id], e.u, e.v, e.predicate) for e in a1.model.edges),
        "K1-double-prime",
    )
    b0 = zero_edge(k2, "b", "d", "f11")
    b1 = zero_edge(b0.model, "a", "e", "f12")
    bmap = {f"f{i}": f"f{i}" for i in range(1, 13)}
    bmap["f10"], bmap["f11"] = "f11", "f10"
    bb = GLModel(
        8,
        V,
        tuple(Edge(bmap[e.id], e.u, e.v, e.predicate) for e in b1.model.edges),
        "K2-double-prime",
    )
    composed = combine_aligned(ConditionedModel((c, Not(c)), (aa, bb)))
    wedge = combine_wedge(ConditionedModel((c, Not(c)), (k1, k2)))
    # Literal simplified M formulas from IJEM pp.263–264, not optimized by our code.
    m1 = [
        O(x1, x2, n6, n7),
        O(A(x1, x2), A(x3, x4), n6, n7),
        O(x3, x4, n6, n7),
        O(A(x1, x2, x3, x4), A(x5, x8), n6, n7),
        TRUE,
        O(x5, x8, n6, n7),
        TRUE,
        O(A(x1, x3), n6, n7),
        O(x2, n6, n7),
    ]
    m2 = [
        O(x1, A(x2, x3, x4), c),
        O(x2, A(x3, x4, x5), c),
        O(x3, A(x6, O(A(x4, x5), x7))),
        O(x4, c),
        O(x5, c),
        O(x6, A(x7, x8, x1)),
        O(x7, A(x8, x1, x2)),
        O(x8, A(x1, x2, x3), c),
        O(A(x4, x5), c),
        O(A(x1, x5, x8), c),
    ]
    # Fig 8a merges K1 gamma (alpha3 in HAIT) with K2 theta (beta8).
    mapping1 = {v: "root" if v == "g" else "a:" + v for v in k1.vertices}
    mapping2 = {v: "root" if v == "t" else "b:" + v for v in k2.vertices}
    mvertices = tuple(dict.fromkeys([*mapping1.values(), *mapping2.values()]))
    medges = [
        Edge(f"k1-f{i + 1}", mapping1[e.u], mapping1[e.v], f0)
        for i, (e, f0) in enumerate(zip(k1.edges, m1, strict=True))
    ]
    medges += [
        Edge(f"k2-f{i + 1}", mapping2[e.u], mapping2[e.v], f0)
        for i, (e, f0) in enumerate(zip(k2.edges, m2, strict=True))
    ]
    m = GLModel(8, mvertices, tuple(medges), "M", dict(k12.metadata))
    # Fig 8b: contract original K1 edges 5 and 7, fuse parallel edges 6/8,
    # and merge original K1 beta with K2 eta. Literal published fused formula.
    contracted = {"a": "a", "b": "b", "g": "g", "d": "d", "e": "e", "z": "e", "h": "a"}
    pmap1 = {v: "root" if contracted[v] == "b" else "a:" + contracted[v] for v in k1.vertices}
    pmap2 = {v: "root" if v == "h" else "b:" + v for v in k2.vertices}
    pvertices = tuple(dict.fromkeys([*pmap1.values(), *pmap2.values()]))
    pedges = [
        Edge(f"k1-f{i + 1}", pmap1[e.u], pmap1[e.v], m1[i])
        for i, e in enumerate(k1.edges)
        if i not in (4, 5, 6, 7)
    ]
    pedges.append(Edge("k1-f10", pmap1["a"], pmap1["e"], O(A(x1, x3), x5, x8, n6, n7)))
    pedges += [
        Edge(f"k2-f{i + 1}", pmap2[e.u], pmap2[e.v], f0)
        for i, (e, f0) in enumerate(zip(k2.edges, m2, strict=True))
    ]
    mp = GLModel(8, pvertices, tuple(pedges), "M-prime", dict(k12.metadata))
    return {
        "K1-prime": k1,
        "K2-prime": k2,
        "K12": k12,
        "K12-prime": kp,
        "K12-composed": composed.model,
        "M-unsimplified": wedge,
        "M": m,
        "M-prime": mp,
    }, [a.record, a0.record, a1.record, b0.record, b1.record, composed.record]


def write_csv(path, rows):
    rows = list(rows)
    with Path(path).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reproduce(root, out, spec_path=None):
    root, out = Path(root), Path(out)
    if spec_path:
        from .model import load_json

        spec = load_json(spec_path)
        model_path = Path(spec_path).parent / spec["model"]
        if not model_path.is_file():
            raise ModelError("BLOCKED_NEEDS_AUTHOR_CONFIRMED_INPUT: missing source model fixture")
        source = load_model(model_path)
        result = check_functions(8, lambda s: operational(source, s), oracle)
        if result.status != "EXHAUSTIVE_PASS":
            raise ModelError(f"paper source fixture fails independent oracle: {result.to_dict()}")
    pdf = root / "artifacts/sources/IJEM-V16-N3-15.pdf"
    if not pdf.is_file():
        raise ModelError("BLOCKED_NEEDS_AUTHOR_CONFIRMED_INPUT: original IJEM PDF missing")
    if len(set(ACCEPTED)) != 22 or any(len(s) != 8 or s.count("0") != 3 for s in ACCEPTED):
        raise ModelError("invalid source special-state transcription")
    out.mkdir(parents=True, exist_ok=True)
    models, lineage = source_models()
    results = []
    truth_rows = []
    mismatches = []
    for s in states(8):
        v = "".join(map(str, s))
        truth_rows.append(
            {
                "state": v,
                "failures": 8 - sum(s),
                "oracle": int(oracle(s)),
                "special": int(v in ACCEPTED),
            }
        )
        for name, m in models.items():
            reference = (
                exceptional(s, 2, B1 if name == "K1-prime" else B2)
                if name in ("K1-prime", "K2-prime")
                else oracle(s)
            )
            actual = operational(m, s)
            row = {
                "model": name,
                "state": v,
                "oracle": int(reference),
                "operational": int(actual),
                "match": int(actual == reference),
            }
            results.append(row)
            if not row["match"]:
                mismatches.append(row)
    metric_rows = []
    for name, pub in PUBLISHED.items():
        measured = model_metrics(models[name]) if name in models else None
        for metric, value in pub.items():
            metric_rows.append(
                {
                    "model": name,
                    "metric": metric,
                    "published": value,
                    "measured": measured[metric] if measured else "",
                    "status": ("MATCH" if measured[metric] == value else "DISCREPANCY")
                    if measured
                    else "NOT_RECONSTRUCTED",
                }
            )
    write_csv(out / "truth_table.csv", truth_rows)
    write_csv(out / "model_results.csv", results)
    write_csv(out / "metric_reproduction.csv", metric_rows)
    inputs = {
        "doi": "10.5815/ijem.2026.03.15",
        "pdf_sha256": sha256(pdf.read_bytes()).hexdigest(),
        "accepted": ACCEPTED,
        "B1": B1,
        "B2": B2,
        "published_table1": PUBLISHED,
        "state_order": "x1..x8, 1=working",
        "human_transcription_review": "PENDING",
        "model_hashes": {name: m.digest for name, m in models.items()},
    }
    (out / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    (out / "lineage.json").write_text(json.dumps(lineage, indent=2) + "\n")
    for name, m in models.items():
        save_model(m, out / (name + ".model.json"))
    checks = {
        "composed_vs_literal": check_models(models["K12-composed"], models["K12"]).to_dict(),
        "K12_vs_prime": check_models(models["K12"], models["K12-prime"]).to_dict(),
        "M_vs_unsimplified": check_models(models["M"], models["M-unsimplified"]).to_dict(),
    }
    summary = {
        "states_per_model": 256,
        "models": len(models),
        "operational_oracle_states": sum(r["oracle"] for r in truth_rows),
        "mismatch_count": len(mismatches),
        "checks": checks,
        "metric_discrepancies": [r for r in metric_rows if r["status"] == "DISCREPANCY"],
        "human_review": "PENDING",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "counterexamples.json").write_text(json.dumps(mismatches, indent=2) + "\n")
    (out / "discrepancies.md").write_text(
        "# Reproduction discrepancies\n\n"
        + json.dumps(summary, indent=2)
        + "\n\nAll four Table 1 graphs and literal formulas reconstructed.\n"
        "Source transcription visually checked by one AI-assisted operator; second human review pending.\n"
    )
    return summary
