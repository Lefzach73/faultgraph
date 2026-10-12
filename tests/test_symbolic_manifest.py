import json
from hashlib import sha256

import pytest

from faultgraph.model import ModelError
from faultgraph.symbolic.study import run


@pytest.mark.parametrize(
    "identifiers", [["../escape"], ["/absolute"], ["a/b"], [".."], [""], ["same", "same"], []]
)
def test_manifest_rejected_before_outputs_or_workers(tmp_path, monkeypatch, identifiers):
    cases = [{"id": v, "family": "toy", "n": 3, "seed": 1, "policy": "single"} for v in identifiers]
    source = tmp_path / "cases.json"
    source.write_text(json.dumps(cases))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": len(cases),
                "dataset_sha256": sha256(source.read_bytes()).hexdigest(),
                "worker_seconds": 1,
                "families": ["toy"],
                "seeds": [1],
            }
        )
    )
    binary = tmp_path / "abc"
    binary.write_bytes(b"unused test placeholder")

    def unexpected(*args, **kwargs):
        pytest.fail("worker launched before invalid manifest was rejected")

    monkeypatch.setattr("faultgraph.symbolic.study.subprocess.run", unexpected)
    output = tmp_path / "results"
    with pytest.raises(ModelError, match="case"):
        run(manifest, output, binary)
    assert not output.exists()
