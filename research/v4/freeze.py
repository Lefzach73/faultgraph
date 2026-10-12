"""Prospective provider-core selection and exact physical-link provenance."""

import json
import random
import shutil
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import networkx as nx

ROOT = Path("research/v4")
SOURCE = Path("work/v3/topology-zoo")
SEEDS = (7013, 8011, 9001, 10007, 11003)


def main():
    if (ROOT / "manifest.json").exists():
        raise ValueError("new manifest required; refusing overwrite")
    used = set()
    for p in Path("research/v3/sources").glob("*.graphml"):
        g = nx.read_graphml(p)
        used.add(str(g.graph.get("Network", p.stem)).strip().casefold())
    old = []
    folders = list(Path("artifacts/studies").glob("*/models")) + [
        Path("artifacts/flagship/native-guard-v2/models")
    ]
    for folder in folders:
        for p in folder.glob("*.json"):
            d = json.loads(p.read_text())
            if not isinstance(d, dict) or d.get("schema_version") != "faultgraph-1":
                continue
            g = nx.Graph()
            g.add_nodes_from(d["vertices"])
            g.add_edges_from((e["u"], e["v"]) for e in d["edges"])
            if len(g) >= 10:
                old.append(g)
    old.extend(nx.Graph(nx.read_graphml(p)) for p in Path("research/v3/sources").glob("*.graphml"))
    selected = []
    log = []
    for path in sorted((SOURCE / "graphml").glob("*.graphml")):
        g = nx.read_graphml(path)
        provider = str(g.graph.get("Network", path.stem)).strip().casefold()
        reasons = []
        if g.is_directed():
            reasons.append("DIRECTED")
        if nx.number_of_selfloops(g):
            reasons.append("SOURCE_SELF_LOOPS")
        if provider in used:
            reasons.append("PREVIOUS_OR_SELECTED_PROVIDER")
        simple = nx.Graph(g)
        blocks = list(nx.biconnected_components(simple))
        core_vertices = (
            max(
                blocks,
                key=lambda s: (
                    len(s),
                    simple.subgraph(s).number_of_edges(),
                    tuple(sorted(map(str, s))),
                ),
            )
            if blocks
            else set()
        )
        core = g.subgraph(core_vertices)
        logical = nx.Graph(core)
        if not 10 <= len(core) <= 24:
            reasons.append("CORE_VERTEX_BOUND")
        if not 12 <= core.number_of_edges() <= 32:
            reasons.append("PHYSICAL_EDGE_BOUND")
        if logical.number_of_edges() - len(core) + 1 < 2:
            reasons.append("INSUFFICIENT_CYCLE_RANK")
        if not reasons and any(
            len(o) == len(core)
            and o.number_of_edges() == logical.number_of_edges()
            and nx.is_isomorphic(o, logical)
            for o in old
        ):
            reasons.append("PREVIOUS_TOPOLOGY")
        status = (
            "EXCLUDED" if reasons else "SELECTED" if len(selected) < 6 else "ELIGIBLE_NOT_SELECTED"
        )
        log.append(
            dict(
                file=path.name,
                provider=provider,
                status=status,
                reasons=reasons,
                source_vertices=len(g),
                core_vertices=len(core),
                physical_edges=core.number_of_edges(),
                logical_edges=logical.number_of_edges(),
                source_sha256=sha256(path.read_bytes()).hexdigest(),
            )
        )
        if status == "SELECTED":
            selected.append((path, g, core.copy()))
            used.add(provider)
    assert len(selected) == 6
    sources = ROOT / "sources"
    sources.mkdir(exist_ok=True)
    for name in ("README.md", "LICENSE", "CITATION.cff"):
        shutil.copy2(SOURCE / name, sources / name)
    cases = []
    for path, whole, core in selected:
        shutil.copy2(path, sources / path.name)
        nodes = sorted(core.nodes, key=str)
        mapping = {v: str(i) for i, v in enumerate(nodes)}
        if core.is_multigraph():
            physical = sorted(
                (min(mapping[a], mapping[b]), max(mapping[a], mapping[b]), str(k))
                for a, b, k in core.edges(keys=True)
            )
        else:
            physical = sorted(
                (min(mapping[a], mapping[b]), max(mapping[a], mapping[b]), "simple")
                for a, b in core.edges
            )
        count = len(physical)
        for policy in ("single", "dual", "shared"):
            for seed in SEEDS:
                n = count * (2 if policy == "dual" else 1) + (3 if policy == "shared" else 0)
                rng = random.Random(seed)
                variables = list(range(1, n + 1))
                rng.shuffle(variables)
                groups = list(range(count))
                rng.shuffle(groups)
                links = []
                for i, (a, b, key) in enumerate(physical):
                    ids = [variables[i]]
                    if policy == "dual":
                        ids.append(variables[count + i])
                    if policy == "shared":
                        ids.append(variables[count + groups[i] % 3])
                    links.append(
                        dict(u=a, v=b, processors=ids, physical_id=i, source_parallel_key=key)
                    )
                cases.append(
                    dict(
                        id=f"{path.stem}-core-{policy}-s{seed}",
                        family=path.stem,
                        policy=policy,
                        seed=seed,
                        n=n,
                        vertices=[mapping[v] for v in nodes],
                        links=links,
                        source_file=path.name,
                        source_sha256=sha256(path.read_bytes()).hexdigest(),
                        source_node_mapping={mapping[v]: str(v) for v in nodes},
                        omitted_source_vertices=sorted(str(v) for v in whole if v not in core),
                        scope="largest biconnected source core subsystem; hypothetical controller rules; physical parallel links retained; not whole-provider availability",
                    )
                )
    (ROOT / "cases.json").write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n")
    (ROOT / "selection.json").write_text(json.dumps(log, indent=2) + "\n")
    manifest = dict(
        study_id="native-chain-v4",
        at=datetime.now(UTC).isoformat(),
        baseline_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        topology_revision=subprocess.check_output(
            ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True
        ).strip(),
        plan_sha256=sha256((ROOT / "PLAN.md").read_bytes()).hexdigest(),
        generator_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        dataset_sha256=sha256((ROOT / "cases.json").read_bytes()).hexdigest(),
        selection_sha256=sha256((ROOT / "selection.json").read_bytes()).hexdigest(),
        families=[p.stem for p, g, c in selected],
        seeds=SEEDS,
        policies=["single", "dual", "shared"],
        cases=len(cases),
        samples=256,
        repeats=5,
        construction_seconds=30,
        verification_ms=60000,
        worker_seconds=180,
        bootstrap_seed=314159,
        bootstrap_replicates=2000,
        primary=">=3/6 clusters: warm build<=0.80 of BOTH native-CUDD and AIG-CUDD; query<=1.10 and RSS<=1.10 of native-CUDD; every arm certified",
        cluster="provider/core; seeds and policies paired, six clusters only",
    )
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "families": manifest["families"],
                "cases": len(cases),
                "n": [min(s["n"] for s in cases), max(s["n"] for s in cases)],
                "dataset_sha256": manifest["dataset_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
