"""Supplemental untouched-optimizer validation on native variable-edge graphs."""
from datetime import datetime, UTC
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import random


def freeze():
    folder=Path("experiments")
    target=folder/"native_validation.json"
    if target.exists():raise SystemExit("refusing to overwrite native frozen manifest")
    cases=[]
    for n in (4,6,8,10,12):
        for seed in range(5):
            rng=random.Random(812000+n*100+seed)
            v=min(n,6)
            pairs=[(i,i+1) for i in range(v-1)]
            pool=[p for p in combinations(range(v),2) if p not in pairs]
            pairs+=rng.sample(pool,n-len(pairs))
            rng.shuffle(pairs)
            cases.append({"kind":"channels","n":n,"seed":seed,"vertices":v,"channels":pairs})
    data=folder/"native_cases.json"
    data.write_text(json.dumps(cases,indent=2,sort_keys=True)+"\n")
    m=json.loads((folder/"study_v1_corrected.json").read_text())
    m.update(study_id="native-validation",dataset=data.name,
        dataset_sha256=sha256(data.read_bytes()).hexdigest(),
        generator_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        frozen_at=datetime.now(UTC).isoformat(),development_families=[],heldout_families=["channels"],
        classification="supplemental diagnostic validation; candidate implementation frozen before generation",
        optimizer_source_sha256=sha256(Path("src/faultgraph/optimize.py").read_bytes()).hexdigest())
    m.pop("correction",None);m.pop("predecessor_manifest_sha256",None)
    target.write_text(json.dumps(m,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"cases":len(cases),"dataset_sha256":m["dataset_sha256"]}))


if __name__=="__main__":freeze()
