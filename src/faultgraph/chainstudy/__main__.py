"""Offline v4 chain compiler and prospective study commands."""

import argparse
import json
from pathlib import Path

from ..model import GLModel, ModelError


def compile_model(model_path, backend, output, timeout_ms):
    from ..research.study import deadline
    from ..symbolic.__main__ import load
    from ..symbolic.chains import NativeCompiled
    from ..symbolic.equivalence import check
    from .study import dump, proof_query

    if type(timeout_ms) is not int or timeout_ms < 1:
        raise ModelError("SMT timeout must be positive")
    paths = {
        name: Path(str(output) + suffix)
        for name, suffix in (
            ("output", ""),
            ("candidate", ".candidate.json"),
            ("certificate", ".certificate.json"),
            ("smt", ".smt2"),
            ("lineage", ".lineage.json"),
        )
    }
    if any(path.exists() for path in paths.values()):
        raise ModelError("new output, candidate, certificate, SMT and lineage paths required")
    original = load(model_path)
    if not isinstance(original, GLModel):
        raise ModelError("compile expects a GL model")
    if backend not in ("direct-sift", "chain-sift"):
        raise ModelError("unknown native symbolic backend")
    with deadline(30):
        compiled = NativeCompiled(original, compress=backend == "chain-sift", reorder=True)
    diagram = compiled.diagram
    certificate = proof_query(
        lambda: check(original, diagram.circuit(), timeout_ms=timeout_ms, smt_path=paths["smt"]),
        timeout_ms,
    )
    target = (
        paths["output"]
        if certificate["status"] == "UNSAT_FINITE_EQUIVALENCE"
        else paths["candidate"]
    )
    dump(target, diagram.to_dict())
    dump(paths["certificate"], certificate)
    dump(
        paths["lineage"],
        {
            "backend": backend,
            "source_model_sha256": original.digest,
            "chains": compiled.lineage,
            "summary_vertices": compiled.reduced_vertices,
            "summary_edges": compiled.reduced_edges,
            "scope": "chain summary graph requires the retained global Boolean obligations",
        },
    )
    return certificate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("study", "worker"):
        command = sub.add_parser(name)
        command.add_argument("cases")
        command.add_argument("--manifest", required=True)
        command.add_argument("--output", required=True)
        command.add_argument("--abc", required=True)
        if name == "worker":
            command.add_argument("--case", type=int, required=True)
            command.add_argument("--arm", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("directory")
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("model")
    compile_parser.add_argument(
        "--backend", choices=("direct-sift", "chain-sift"), default="chain-sift"
    )
    compile_parser.add_argument("--output", required=True)
    compile_parser.add_argument("--timeout-ms", type=int, default=60000)
    args = parser.parse_args()
    if args.command == "compile":
        result = compile_model(args.model, args.backend, args.output, args.timeout_ms)
        code = (
            0
            if result["status"] == "UNSAT_FINITE_EQUIVALENCE"
            else 1
            if result["status"] == "COUNTEREXAMPLE"
            else 3
        )
    else:
        from .study import analyze, load_inputs, run, worker

        if args.command == "study":
            result = run(args.cases, args.manifest, args.output, args.abc)
            code = 0 if result["status"] == "COMPLETE" else 3
        elif args.command == "worker":
            cases, manifest = load_inputs(args.cases, args.manifest)
            if not 0 <= args.case < len(cases):
                raise ModelError("case index outside manifest")
            result = worker(cases[args.case], manifest, args.arm, args.output, args.abc)
            code = 0 if result["status"] == "COMPLETE" else 3
            result = {key: result[key] for key in ("case", "arm", "status")}
        else:
            result = analyze(args.directory)
            code = 0 if result["complete"] else 3
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TimeoutError as error:
        print(json.dumps({"status": "TIMEOUT", "error": str(error)}))
        raise SystemExit(3) from error
    except (ValueError, OSError, ImportError, KeyError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}))
        raise SystemExit(2) from error
