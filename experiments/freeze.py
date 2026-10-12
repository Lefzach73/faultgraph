"""Run before candidate implementation. Never rewrite an existing frozen dataset."""
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import random

FAMILIES = ("threshold", "line", "ring", "exceptional", "conditional", "paired", "corner")


def freeze(root=Path(".")):
    target = root/"experiments/study_v1.json"
    if target.exists():
        raise SystemExit("refusing to replace frozen manifest")
    cases = []
    for family in FAMILIES:
        for n in (4,6,8,10,12):
            for seed in range(5):
                rng = random.Random(10000*FAMILIES.index(family)+100*n+seed)
                spec = {"kind":family,"n":n,"seed":seed,"shape":rng.choice(["path","star"]),"size":rng.randint(3,6)}
                if family == "threshold":
                    spec["required"] = n-2
                elif family in ("line","ring"):
                    spec["k"] = 2+seed%2
                elif family == "exceptional":
                    spec["max_failures"] = 2
                    failed = rng.sample(list(combinations(range(n),3)), min(3, n))
                    spec["accepted"] = [''.join('0' if i in f else '1' for i in range(n)) for f in failed]
                elif family == "conditional":
                    spec.update(high=n-1,low=n-2)
                elif family == "corner":
                    spec["operational"] = bool(seed%2)
                cases.append(spec)
    dataset = root/"experiments/frozen_cases.json"
    dataset.write_text(json.dumps(cases,indent=2,sort_keys=True)+"\n")
    manifest = {"study_id":"study-v1","classification":"diagnostic exploratory study; no confirmatory novelty claim",
        "frozen_at":datetime.now(timezone.utc).isoformat(),"dataset":"frozen_cases.json",
        "dataset_sha256":sha256(dataset.read_bytes()).hexdigest(),
        "generator_sha256":sha256(Path(__file__).read_bytes()).hexdigest(),
        "development_families":["threshold","line","conditional"],
        "heldout_families":["ring","exceptional","paired","corner"],
        "optimizer_predeclared":"local-v1 simplification plus zero-edge removal and unit-edge contraction; no oracle-guided synthesis",
        "optimizer_budget":32,"operation_growth_bound":0,"per_model_timeout_seconds":30,
        "evaluation_samples":128,"timing_repeats":5,"mc_samples":5000,
        "working_probability_grid":[0.8,0.9,0.99],"common_cause_q":0.1,
        "primary_statistical_repeats":None,"reason":"pilot only; no inferential superiority testing",
        "excluded_family":"F06 paper-specific inter-subsystem construction pending verified mapping",
        "dataset_license":"new generated synthetic data; public code/data license pending owner review"}
    target.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"models":len(cases),"manifest":str(target),"sha256":manifest["dataset_sha256"]}))


if __name__ == "__main__":
    freeze()

