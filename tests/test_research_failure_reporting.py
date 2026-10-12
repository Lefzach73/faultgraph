import csv
import json

import pytest

from faultgraph.expr import FALSE, Var
from faultgraph.model import Edge, GLModel, ModelError
from faultgraph.research.guarded import search
from faultgraph.research.kernel import expression_mask
from faultgraph.research.study import analyze


def test_constant_bitset_respects_processor_limit():
    with pytest.raises(ModelError):
        expression_mask(FALSE, 13)


def test_cut_search_declines_unbounded_graph_enumeration():
    vertices = tuple(map(str, range(13)))
    model = GLModel(
        1,
        vertices,
        tuple(Edge(f"e{i}", vertices[i], vertices[(i + 1) % 13], Var(1)) for i in range(13)),
    )
    assert search(model, budget=1)["status"] == "NOT_CHECKED"


@pytest.mark.parametrize("arms", [[], ["local", "greedy-global", "greedy-cut", "beam-cut"]])
def test_missing_comparators_never_count_as_complete(tmp_path, arms):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"families": ["fixture"], "bootstrap_seed": 1, "bootstrap_family_replicates": 10}
        )
    )
    (tmp_path / "cases.json").write_text(json.dumps([{"id": "case", "family": "fixture"}]))
    fields = [
        "case",
        "family",
        "seed",
        "arm",
        "status",
        "mismatch_count",
        "dag_p50_ms",
        "dag_ops",
        "construction_ms",
        "peak_RSS_MB",
        "vertices",
        "edges",
        "total",
        "model_hash",
    ]
    with (tmp_path / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for arm in arms:
            writer.writerow(
                dict(
                    zip(
                        fields,
                        ["case", "fixture", 1, arm, "COMPLETE", 0, 1, 2, 1, 20, 3, 3, 2, arm],
                        strict=True,
                    )
                )
            )
    result = analyze(tmp_path)
    assert result["H_correctness"] == "INCOMPLETE"
    assert result["H_guard"] == "INCOMPLETE"
