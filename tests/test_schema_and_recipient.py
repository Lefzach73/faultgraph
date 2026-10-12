import json
from itertools import product
from pathlib import Path

import jsonschema
import pytest

from faultgraph.evaluator import operational
from faultgraph.model import load_model
from faultgraph.subsystems import limited_vector, source_recipient

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("limited", [False, True])
def test_published_virtual_recipient_model_exact(limited):
    model = source_recipient(limited)
    assert all(
        operational(model, s) == (sum(s) >= 4) for s in product((0, 1), repeat=model.num_processors)
    )


def test_resource_limitation_exact():
    for s in product((0, 1), repeat=5):
        assert sum(limited_vector(s)) == min(4, sum(s))


def test_json_schema_matches_valid_fixture():
    schema = json.loads((ROOT / "schema/gl-model.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    d = load_model(ROOT / "examples/triangle_2of3.model.json").to_dict()
    jsonschema.validate(d, schema)
    d["edges"][0]["predicate"] = {"type": "var", "index": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(d, schema)
