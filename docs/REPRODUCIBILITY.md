# Reproducibility

The core needs Python 3.12+ only. Full scientific tests use actual CUDD, Z3 and ABC;
they do not replace those tools with mock benchmark results.

```sh
python3 -m venv .venv
DD_FETCH=1 DD_CUDD=1 .venv/bin/python -m pip install -r research/v3/requirements.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -c 'import dd.cudd; import z3; print(z3.get_version_string())'
git clone https://github.com/berkeley-abc/abc.git work/v3/abc
git -C work/v3/abc checkout --detach 8b2a6fd05e7b0d922c07202d9af5e6bffe79a23d
make -C work/v3/abc -j2 ABC_USE_NO_READLINE=1
.venv/bin/python scripts/verify_public_export.py
.venv/bin/python -m pytest -q
```

Installing dependencies and obtaining ABC require network access. After setup,
compilation, exact checking, evaluation and study execution run offline. A C/C++
compiler and make are needed when CUDD/ABC must be built from source.

Compile and independently check a model before using its portable decision diagram:

```sh
mkdir -p work/demo
.venv/bin/python -m faultgraph.chainstudy compile examples/triangle_2of3.model.json --backend chain-sift --output work/demo/triangle.json
.venv/bin/python -m faultgraph.symbolic evaluate work/demo/triangle.json --state 110
.venv/bin/python -m faultgraph.symbolic reliability work/demo/triangle.json --probabilities fixtures/simple/p.json
```

Compile writes a certified output only after `UNSAT_FINITE_EQUIVALENCE`; unresolved
attempts retain a separately named candidate and certificate. Output paths must
be new, so previous evidence is never overwritten.

Rerun the 90-case v4 comparison, using a new output directory:

```sh
.venv/bin/python -m faultgraph.chainstudy study research/v4/cases.json --manifest research/v4/manifest.json --output work/v4-public-replication --abc work/v3/abc/abc
.venv/bin/python -m faultgraph.chainstudy analyze work/v4-public-replication
```

The raw new run includes per-worker queries, outcomes and timings. Hardware affects
time and memory; compare exact model/state/truth hashes separately from runtime.
The historical summary files in `artifacts/flagship` remain untouched.

`docs/MODEL_SEMANTICS.md` records the original v1 finite-enumeration semantics.
The later optional symbolic checker additionally supports exact SMT checks up to
64 component variables under its explicit bounds. The original v1 statement about
having no general scalable symbolic checker refers to that earlier backend.
The chain compiler's summary graph is valid only together with its retained global
Boolean obligations; it is not a standalone drop-in graph after discarding them.
