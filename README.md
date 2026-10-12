# FaultGraph Lab

[![Scientific validation](https://github.com/Lefzach73/faultgraph/actions/workflows/public-ci.yml/badge.svg)](https://github.com/Lefzach73/faultgraph/actions/workflows/public-ci.yml)

**Scientific software for understanding which failures a system can tolerate.**

FaultGraph Lab models a system as an undirected graph whose connections depend on
Boolean component states. It evaluates operational connectivity, calculates
reliability, and compiles models into more efficient representations with exact
finite-instance equivalence checks.

## What it does

- Validates a safe Boolean-expression AST and strict graph/model JSON.
- Evaluates all required vertices, including isolated ones, using explicit `1 = working` semantics.
- Reproduces the published eight-processor example against an independent oracle.
- Supports exact small-domain reliability, Monte Carlo estimates and explicit dependence models.
- Builds AIGs and CUDD decision diagrams, runs pinned ABC synthesis, and retains solver counterexamples or unresolved outcomes.
- Implements guarded chain compression: internal-vertex obligations remain part of the model.

## Quick start

Clone [Lefzach73/faultgraph](https://github.com/Lefzach73/faultgraph) and run the commands from its root.
Python 3.12 or newer is required. The core runtime has no third-party dependencies.
The package installation below needs network access only when dependencies are not
already cached; model evaluation and the CLI run offline.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m faultgraph validate examples/triangle_2of3.model.json
.venv/bin/python -m faultgraph evaluate examples/triangle_2of3.model.json --state 110
.venv/bin/python -m faultgraph reliability examples/triangle_2of3.model.json --probabilities fixtures/simple/p.json --samples 5000 --seed 17
```

The three-component example works when at least two components work. With each
working independently with probability 0.9, its exact reliability is 0.972.

## Reproduce and test

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/verify_public_export.py
.venv/bin/python -m pytest -q
.venv/bin/python -m faultgraph reproduce-paper --output work/paper8
.venv/bin/python -m faultgraph reproduce-donors --include-recipients --output work/donors
```

Optional CUDD/SMT/ABC tests report explicit skips if their dependencies are absent.
The public scientific CI builds those dependencies and runs all **228 retained
tests**, including the six-arm development study. See [advanced setup and the
90-case reproduction command](docs/REPRODUCIBILITY.md).

## Evidence and limits

The archived v4 study covered **90 cases in six historical provider/core clusters**
and certified **540/540 outputs**. All six clusters met its predeclared practical
threshold; cluster warm-build ratios were 0.354–0.505 against direct CUDD.
The archived Linux run matched all 540 output, input-state and truth hashes.
These are bounded results for hypothetical controller policies on historical
network subsystems; they do not establish universal speedups or a new theorem.

The earlier v2 optimization hypothesis was refuted; the v3 primary outcome was
inconclusive. Those results are retained in the [results overview](docs/RESULTS.md).
Human scientific review and novelty priority remain unestablished.

[Read the v4 technical report](artifacts/flagship/review-v4/TECHNICAL_REPORT.pdf) ·
[Model semantics](docs/MODEL_SEMANTICS.md) ·
[Paper reproduction notes](docs/PAPER_REPRODUCTION_NOTES.md)

## Research attribution

The graph-logical modeling methods are prior coauthored research by Vitaliy
Romankevich, Kostiantyn Morozov, Alexei Romankevich, Petro Malezhyk, Lefteris
Zacharioudakis, and, for the related HAIT/AAIT methods, Daniil Halytsky.
The software and computational audits are disclosed as AI-assisted implementation;
commit authorship is not a claim of sole scientific invention.

[Primary paper](https://doi.org/10.5815/ijem.2026.03.15) ·
[Citation metadata](CITATION.cff) · [Third-party notices](THIRD_PARTY_NOTICES.md)

This is a curated source-available edition with rights reserved; no general
software license has yet been selected. The papers and Topology Zoo data retain
CC BY 4.0. See [publication scope and provenance](PUBLICATION.md).
